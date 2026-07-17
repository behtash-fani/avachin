import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import APIC, ID3, TIT2, TXXX


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smart_music_organizer",
    ROOT / "smart_music_organizer.py",
)
assert SPEC and SPEC.loader
smo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smo
SPEC.loader.exec_module(smo)


class SmartMusicOrganizerTests(unittest.TestCase):
    def test_full_id3_snapshot_restores_custom_frames_and_artwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            song = root / "song.mp3"
            backup = root / "snapshot.id3"

            tags = ID3()
            tags.add(TIT2(encoding=3, text=["Original Title"]))
            tags.add(TXXX(encoding=3, desc="CUSTOM_TEST", text=["keep-me"]))
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=b"cover-bytes",
                )
            )
            tags.save(song, v2_version=4)

            smo.snapshot_id3(song, backup)

            changed = ID3(song)
            changed.delall("TXXX:CUSTOM_TEST")
            changed.delall("APIC:Cover")
            changed.add(TIT2(encoding=3, text=["Changed Title"]))
            changed.add(TXXX(encoding=3, desc="BITRATE", text=["320 kbps"]))
            changed.save(song, v2_version=4)

            smo.restore_id3_snapshot(song, backup, "2.4")
            restored = ID3(song)

            self.assertEqual(restored.getall("TIT2")[0].text, ["Original Title"])
            self.assertEqual(
                restored.getall("TXXX:CUSTOM_TEST")[0].text,
                ["keep-me"],
            )
            self.assertEqual(
                restored.getall("APIC:Cover")[0].data,
                b"cover-bytes",
            )
            self.assertEqual(restored.getall("TXXX:BITRATE"), [])

    def test_apply_transaction_rolls_back_when_final_commit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp3"
            target = root / "Artist" / "Album" / "Song - Artist.mp3"
            run_dir = root / "run"
            app_dir = root / "app"

            tags = ID3()
            tags.add(TIT2(encoding=3, text=["Original Title"]))
            tags.add(TXXX(encoding=3, desc="CUSTOM_TEST", text=["keep-me"]))
            tags.save(source, v2_version=4)

            journal = smo.RunJournal(
                run_dir=run_dir,
                app_dir=app_dir,
                metadata={
                    "input_root": str(root),
                    "output_root": str(root),
                    "mode": "apply",
                    "id3_version": "2.4",
                },
                fsync=False,
            )

            candidate = smo.Candidate(
                source="test",
                title="Changed Title",
                artist="Artist",
                album="Album",
                album_artist="Artist",
                confidence=100.0,
            )
            audio = smo.AudioInfo(
                tags=smo.Tags(title="Original Title", artist="Artist"),
            )

            real_safe_rename = smo.safe_rename

            def fail_final_commit(left: Path, right: Path) -> None:
                if left.name.startswith(".__smart_music_txn_") and right == target:
                    raise OSError("forced final commit failure")
                real_safe_rename(left, right)

            with patch.object(smo, "safe_rename", side_effect=fail_final_commit):
                change = smo.process_mp3(
                    source=source,
                    target=target,
                    duplicate_root=root / "_Duplicates",
                    artist_folder="Artist",
                    album_folder="Album",
                    candidate=candidate,
                    audio=audio,
                    copy_mode=False,
                    id3_version="2.4",
                    write_bitrate_tag=False,
                    journal=journal,
                    backup_root=run_dir / "tag_backups",
                )

            journal.close("completed-with-errors")

            self.assertEqual(change["status"], "rolled-back-error")
            self.assertTrue(source.exists())
            self.assertFalse(target.exists())
            restored = ID3(source)
            self.assertEqual(restored.getall("TIT2")[0].text, ["Original Title"])
            self.assertEqual(
                restored.getall("TXXX:CUSTOM_TEST")[0].text,
                ["keep-me"],
            )

            manifest = json.loads((run_dir / "changes.json").read_text())
            self.assertEqual(manifest["changes"][0]["status"], "rolled-back-error")

    def test_crash_recovery_restores_pending_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp3"
            run_dir = root / "run"
            app_dir = root / "app"

            tags = ID3()
            tags.add(TIT2(encoding=3, text=["Original Title"]))
            tags.add(TXXX(encoding=3, desc="CUSTOM_TEST", text=["keep-me"]))
            tags.save(source, v2_version=4)

            journal = smo.RunJournal(
                run_dir=run_dir,
                app_dir=app_dir,
                metadata={
                    "input_root": str(root),
                    "output_root": str(root),
                    "mode": "apply",
                    "id3_version": "2.4",
                },
                fsync=False,
            )
            change_id = "pending-test"
            backup = run_dir / "tag_backups" / f"{change_id}.id3"
            staging = root / f".__smart_music_txn_{change_id}.mp3"
            target = root / "Artist" / "Album" / "Song - Artist.mp3"
            smo.snapshot_id3(source, backup)
            change = journal.begin({
                "id": change_id,
                "kind": "mp3",
                "mode": "in_place",
                "source": str(source),
                "final": str(target),
                "staging": str(staging),
                "tag_snapshot": str(backup),
            })
            smo.safe_rename(source, staging)
            changed = ID3(staging)
            changed.add(TIT2(encoding=3, text=["Changed Title"]))
            changed.save(staging, v2_version=4)

            # Simulate a hard crash: no journal.finish() and no journal.close().
            smo.recover_active_run(app_dir)

            self.assertTrue(source.exists())
            self.assertFalse(staging.exists())
            restored = ID3(source)
            self.assertEqual(restored.getall("TIT2")[0].text, ["Original Title"])
            self.assertEqual(
                restored.getall("TXXX:CUSTOM_TEST")[0].text,
                ["keep-me"],
            )
            manifest = json.loads((run_dir / "changes.json").read_text())
            self.assertEqual(manifest["status"], "recovered")
            self.assertEqual(manifest["changes"][0]["status"], "recovered-rollback")

    def test_single_instance_lock_blocks_second_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            first = smo.AppRunLock(app_dir)
            second = smo.AppRunLock(app_dir)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_sidecars_follow_the_dominant_album_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            cover = source_dir / "cover.jpg"
            cover.write_bytes(b"cover")
            album_dir = root / "Artist" / "Album"

            mapping = {source_dir: smo.Counter({album_dir: 3})}
            target = smo.sidecar_target_for(cover, mapping, smo.DEFAULT_CONFIG)

            self.assertEqual(target, album_dir / "cover.jpg")

    def test_missing_album_uses_fast_catalog_path_without_musicbrainz(self):
        class FastClient:
            apple_country = "US"

            def spotify_enabled(self):
                return False

            def apple_search(self, title, artist):
                return [{
                    "kind": "song",
                    "trackName": title,
                    "artistName": artist,
                    "collectionName": "Found Album",
                    "collectionArtistName": artist,
                    "trackTimeMillis": 100000,
                    "trackId": 1,
                }]

            def musicbrainz_search(self, *args, **kwargs):
                raise AssertionError("MusicBrainz should not be needed for a strong fast match")

        audio = smo.AudioInfo(
            tags=smo.Tags(title="Song", artist="Artist"),
            duration_seconds=100,
        )
        candidate, errors = smo.determine_candidate(
            source=Path("Song - Artist.mp3"),
            audio=audio,
            default_artist="",
            normalize_persian=False,
            config=smo.DEFAULT_CONFIG,
            client=FastClient(),
            min_confidence=85,
            verify_online=False,
            offline=False,
            unknown_artist_folder="_Unknown Artist",
        )
        self.assertEqual(errors, [])
        self.assertEqual(candidate.source, "apple")
        self.assertEqual(candidate.album, "Found Album")

    def test_output_inside_input_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "Organized"
            self.assertTrue(smo.path_is_within(nested, root))
            self.assertFalse(smo.path_is_within(root, nested))

    def test_target_path_is_shortened_to_configured_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artist, album, filename, target = smo.fit_target_path(
                root,
                "A" * 180,
                "B" * 180,
                ("C" * 220) + ".mp3",
                240,
            )
            self.assertLessEqual(len(str(target)), 240)
            self.assertTrue(filename.endswith(".mp3"))
            self.assertTrue(artist)
            self.assertTrue(album)

    def test_quick_hash_changes_when_file_edges_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.bin"
            right = root / "right.bin"
            left.write_bytes(b"a" * 600_000)
            right.write_bytes(b"a" * 599_999 + b"b")
            self.assertNotEqual(
                smo.quick_hash_file(left),
                smo.quick_hash_file(right),
            )

    def test_generic_source_brand_suffix_is_removed_without_name_hardcoding(self):
        cleaned = smo.clean_artist_label(
            "Example Singer - SomeMusicSite",
            False,
            smo.DEFAULT_CONFIG,
        )
        self.assertEqual(cleaned, "Example Singer")

    def test_multi_credit_track_uses_primary_identity_not_joint_folder(self):
        solo_plans = [
            smo.TrackPlan(
                source=Path(f"solo-{index}.mp3"),
                audio=smo.AudioInfo(tags=smo.Tags(artist="Lead Singer")),
                candidate=smo.Candidate(
                    source="spotify",
                    title=f"Solo {index}",
                    artist="Lead Singer",
                    album_artist="Lead Singer",
                    evidence={
                        "track_artist_entities": ["Lead Singer"],
                        "track_artist_keys": ["spotify:lead"],
                        "track_artist_atomic": True,
                        "album_artist_entities": ["Lead Singer"],
                        "album_artist_keys": ["spotify:lead"],
                        "album_artist_atomic": True,
                    },
                ),
            )
            for index in range(3)
        ]
        collaboration = smo.TrackPlan(
            source=Path("collab.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Lead Singer & Guest Person")),
            candidate=smo.Candidate(
                source="spotify",
                title="Collaboration",
                artist="Lead Singer, Guest Person",
                album_artist="Lead Singer",
                evidence={
                    "track_artist_entities": ["Lead Singer", "Guest Person"],
                    "track_artist_keys": ["spotify:lead", "spotify:guest"],
                    "track_artist_atomic": False,
                    "album_artist_entities": ["Lead Singer"],
                    "album_artist_keys": ["spotify:lead"],
                    "album_artist_atomic": True,
                },
            ),
        )
        plans = solo_plans + [collaboration]
        profile = smo.build_profile_from_plans(plans, False, smo.DEFAULT_CONFIG)
        folder = smo.primary_artist_for_folder(
            collaboration.candidate,
            collaboration.audio.tags,
            profile,
            "_Unknown Artist",
            False,
            smo.DEFAULT_CONFIG,
            None,
        )
        self.assertEqual(folder, "Lead Singer")
        self.assertNotIn("Guest Person", folder)

    def test_composer_role_does_not_own_folder_when_performer_has_library_evidence(self):
        performer_plans = [
            smo.TrackPlan(
                source=Path(f"performer-{index}.mp3"),
                audio=smo.AudioInfo(tags=smo.Tags(artist="Actual Performer")),
                candidate=smo.Candidate(
                    source="existing-tags",
                    title=f"Song {index}",
                    artist="Actual Performer",
                    album_artist="Actual Performer",
                    evidence=smo.local_credit_evidence(
                        "Actual Performer",
                        "Actual Performer",
                        False,
                        smo.DEFAULT_CONFIG,
                    ),
                ),
            )
            for index in range(4)
        ]
        mixed = smo.TrackPlan(
            source=Path("mixed.mp3"),
            audio=smo.AudioInfo(
                tags=smo.Tags(
                    artist="Composer Person & Actual Performer",
                    composer="Composer Person",
                )
            ),
            candidate=smo.Candidate(
                source="local-cleanup",
                title="Mixed Credit Song",
                artist="Composer Person & Actual Performer",
                album_artist="Composer Person & Actual Performer",
                evidence=smo.local_credit_evidence(
                    "Composer Person & Actual Performer",
                    "Composer Person & Actual Performer",
                    False,
                    smo.DEFAULT_CONFIG,
                ),
            ),
        )
        plans = performer_plans + [mixed]
        profile = smo.build_profile_from_plans(plans, False, smo.DEFAULT_CONFIG)
        folder = smo.primary_artist_for_folder(
            mixed.candidate,
            mixed.audio.tags,
            profile,
            "_Unknown Artist",
            False,
            smo.DEFAULT_CONFIG,
            None,
        )
        self.assertEqual(folder, "Actual Performer")

    def test_provider_confirmed_group_stays_atomic_while_member_solo_work_stays_separate(self):
        group = smo.TrackPlan(
            source=Path("group.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Alpha & Beta")),
            candidate=smo.Candidate(
                source="musicbrainz",
                title="Group Song",
                artist="Alpha & Beta",
                album_artist="Alpha & Beta",
                evidence={
                    "track_artist_entities": ["Alpha & Beta"],
                    "track_artist_keys": ["mb:group-id"],
                    "track_artist_atomic": True,
                    "album_artist_entities": ["Alpha & Beta"],
                    "album_artist_keys": ["mb:group-id"],
                    "album_artist_atomic": True,
                },
            ),
        )
        solo = smo.TrackPlan(
            source=Path("solo.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Alpha")),
            candidate=smo.Candidate(
                source="musicbrainz",
                title="Solo Song",
                artist="Alpha",
                album_artist="Alpha",
                evidence={
                    "track_artist_entities": ["Alpha"],
                    "track_artist_keys": ["mb:solo-id"],
                    "track_artist_atomic": True,
                    "album_artist_entities": ["Alpha"],
                    "album_artist_keys": ["mb:solo-id"],
                    "album_artist_atomic": True,
                },
            ),
        )
        profile = smo.build_profile_from_plans([group, solo], False, smo.DEFAULT_CONFIG)
        group_folder = smo.primary_artist_for_folder(
            group.candidate, group.audio.tags, profile,
            "_Unknown Artist", False, smo.DEFAULT_CONFIG, None,
        )
        solo_folder = smo.primary_artist_for_folder(
            solo.candidate, solo.audio.tags, profile,
            "_Unknown Artist", False, smo.DEFAULT_CONFIG, None,
        )
        self.assertEqual(group_folder, "Alpha & Beta")
        self.assertEqual(solo_folder, "Alpha")

    def test_existing_musicbrainz_artist_id_preserves_group_as_atomic(self):
        audio = smo.AudioInfo(
            tags=smo.Tags(
                title="Group Song",
                artist="Alpha & Beta",
                albumartist="Alpha & Beta",
                musicbrainz_artistid="group-id",
            )
        )
        candidate = smo.candidate_from_existing_tags(
            audio,
            False,
            smo.DEFAULT_CONFIG,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.evidence["track_artist_entities"], ["Alpha & Beta"])
        self.assertEqual(candidate.evidence["track_artist_keys"], ["mb:group-id"])

        plan = smo.TrackPlan(Path("group.mp3"), audio, candidate)
        profile = smo.build_profile_from_plans([plan], False, smo.DEFAULT_CONFIG)
        folder = smo.primary_artist_for_folder(
            candidate,
            audio.tags,
            profile,
            "_Unknown Artist",
            False,
            smo.DEFAULT_CONFIG,
            None,
        )
        self.assertEqual(folder, "Alpha & Beta")

    def test_stable_provider_identity_merges_spelling_variants(self):
        plans = []
        for index, name in enumerate(["Canonical Name", "Canonical Name", "نام دیگر"]):
            plans.append(
                smo.TrackPlan(
                    source=Path(f"alias-{index}.mp3"),
                    audio=smo.AudioInfo(tags=smo.Tags(artist=name)),
                    candidate=smo.Candidate(
                        source="musicbrainz",
                        title=f"Song {index}",
                        artist=name,
                        album_artist=name,
                        evidence={
                            "track_artist_entities": [name],
                            "track_artist_keys": ["mb:same-identity"],
                            "track_artist_atomic": True,
                            "album_artist_entities": [name],
                            "album_artist_keys": ["mb:same-identity"],
                            "album_artist_atomic": True,
                        },
                    ),
                )
            )
        profile = smo.build_profile_from_plans(plans, False, smo.DEFAULT_CONFIG)
        folders = {
            smo.primary_artist_for_folder(
                plan.candidate, plan.audio.tags, profile,
                "_Unknown Artist", False, smo.DEFAULT_CONFIG, None,
            )
            for plan in plans
        }
        self.assertEqual(folders, {"Canonical Name"})

    def test_concatenated_known_identities_are_not_kept_as_a_micro_folder(self):
        plans = []
        for name in ("Singer One", "Singer Two"):
            for index in range(3):
                plans.append(
                    smo.TrackPlan(
                        source=Path(f"{name}-{index}.mp3"),
                        audio=smo.AudioInfo(tags=smo.Tags(artist=name)),
                        candidate=smo.Candidate(
                            source="existing-tags",
                            title=f"Song {index}",
                            artist=name,
                            album_artist=name,
                            evidence=smo.local_credit_evidence(
                                name, name, False, smo.DEFAULT_CONFIG
                            ),
                        ),
                    )
                )

        malformed = smo.TrackPlan(
            source=Path("malformed.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Singer One Singer Two")),
            candidate=smo.Candidate(
                source="existing-tags",
                title="Combined Credit",
                artist="Singer One Singer Two",
                album_artist="Singer One Singer Two",
                evidence=smo.local_credit_evidence(
                    "Singer One Singer Two",
                    "Singer One Singer Two",
                    False,
                    smo.DEFAULT_CONFIG,
                ),
            ),
        )
        plans.append(malformed)
        profile = smo.build_profile_from_plans(plans, False, smo.DEFAULT_CONFIG)
        folder = smo.primary_artist_for_folder(
            malformed.candidate,
            malformed.audio.tags,
            profile,
            "_Unknown Artist",
            False,
            smo.DEFAULT_CONFIG,
            None,
        )
        self.assertIn(folder, {"Singer One", "Singer Two"})
        self.assertNotEqual(folder, "Singer One Singer Two")

    def test_secondary_only_online_credit_cannot_replace_strong_local_performer(self):
        online = smo.Candidate(
            source="spotify",
            title="Song",
            artist="Other Lead, Local Performer",
            album_artist="Other Lead",
            evidence={
                "track_artist_entities": ["Other Lead", "Local Performer"],
                "track_artist_keys": ["spotify:other", "spotify:local"],
                "track_artist_atomic": False,
                "album_artist_entities": ["Other Lead"],
                "album_artist_keys": ["spotify:other"],
                "album_artist_atomic": True,
            },
        )
        audio = smo.AudioInfo(tags=smo.Tags(title="Song", artist="Local Performer"))
        self.assertTrue(
            smo.online_candidate_conflicts_with_local_performer(
                online,
                audio,
                False,
                smo.DEFAULT_CONFIG,
            )
        )

    def test_artist_level_identity_lookup_merges_cross_script_aliases_once_per_artist(self):
        class IdentityClient:
            def __init__(self):
                self.queries = []

            def musicbrainz_artist_search(self, artist, limit=5):
                self.queries.append(artist)
                return [{
                    "id": "shared-id",
                    "name": "Canonical Artist",
                    "score": 100,
                    "aliases": [
                        {"name": "Canonical Artist"},
                        {"name": "نام هنرمند"},
                    ],
                }]

        plans = []
        for index, name in enumerate([
            "Canonical Artist",
            "Canonical Artist",
            "نام هنرمند",
            "نام هنرمند",
        ]):
            evidence = smo.local_credit_evidence(
                name,
                name,
                False,
                smo.DEFAULT_CONFIG,
            )
            plans.append(
                smo.TrackPlan(
                    source=Path(f"identity-{index}.mp3"),
                    audio=smo.AudioInfo(tags=smo.Tags(artist=name)),
                    candidate=smo.Candidate(
                        source="existing-tags",
                        title=f"Song {index}",
                        artist=name,
                        album_artist=name,
                        evidence=evidence,
                    ),
                )
            )

        client = IdentityClient()
        resolved, errors = smo.resolve_artist_identities_online(
            plans,
            client,
            smo.DEFAULT_CONFIG,
            offline=False,
        )
        self.assertEqual(errors, [])
        self.assertGreaterEqual(resolved, 4)
        self.assertEqual(client.queries, ["نام هنرمند"])

        profile = smo.build_profile_from_plans(plans, False, smo.DEFAULT_CONFIG)
        folders = {
            smo.primary_artist_for_folder(
                plan.candidate, plan.audio.tags, profile,
                "_Unknown Artist", False, smo.DEFAULT_CONFIG, None,
            )
            for plan in plans
        }
        self.assertEqual(folders, {"Canonical Artist"})

    def test_artist_identity_min_tracks_counts_distinct_files_not_track_and_album(self):
        class IdentityClient:
            def __init__(self):
                self.queries = []

            def musicbrainz_artist_search(self, artist, limit=5):
                self.queries.append(artist)
                return []

        plan = smo.TrackPlan(
            source=Path("single.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="One Song Artist")),
            candidate=smo.Candidate(
                source="existing-tags",
                title="Single",
                artist="One Song Artist",
                album_artist="One Song Artist",
                evidence=smo.local_credit_evidence(
                    "One Song Artist",
                    "One Song Artist",
                    False,
                    smo.DEFAULT_CONFIG,
                ),
            ),
        )
        config = dict(smo.DEFAULT_CONFIG)
        config["artist_identity_mode"] = "deep"
        config["artist_identity_lookup_min_tracks"] = 2

        client = IdentityClient()
        resolved, errors = smo.resolve_artist_identities_online(
            [plan], client, config, offline=False
        )

        self.assertEqual(resolved, 0)
        self.assertEqual(errors, [])
        self.assertEqual(client.queries, [])

    def test_smart_identity_mode_skips_clear_latin_catalog(self):
        class IdentityClient:
            def __init__(self):
                self.queries = []

            def musicbrainz_artist_search(self, artist, limit=5):
                self.queries.append(artist)
                return []

        plans = []
        for artist_index in range(139):
            artist = f"Clear Artist {artist_index}"
            for track_index in range(2):
                plans.append(
                    smo.TrackPlan(
                        source=Path(f"{artist_index}-{track_index}.mp3"),
                        audio=smo.AudioInfo(tags=smo.Tags(artist=artist)),
                        candidate=smo.Candidate(
                            source="existing-tags",
                            title=f"Song {track_index}",
                            artist=artist,
                            album_artist=artist,
                            evidence=smo.local_credit_evidence(
                                artist, artist, False, smo.DEFAULT_CONFIG
                            ),
                        ),
                    )
                )

        client = IdentityClient()
        resolved, errors = smo.resolve_artist_identities_online(
            plans, client, dict(smo.DEFAULT_CONFIG), offline=False
        )

        self.assertEqual(resolved, 0)
        self.assertEqual(errors, [])
        self.assertEqual(client.queries, [])

    def test_artist_identity_time_budget_caps_slow_lookup_stage(self):
        import time

        class SlowIdentityClient:
            def __init__(self):
                self.queries = []

            def musicbrainz_artist_search(self, artist, limit=5):
                self.queries.append(artist)
                time.sleep(0.05)
                return []

        plans = []
        # A Latin identity makes cross-script alias resolution useful.
        plans.append(
            smo.TrackPlan(
                source=Path("latin.mp3"),
                audio=smo.AudioInfo(tags=smo.Tags(artist="Latin Artist")),
                candidate=smo.Candidate(
                    source="existing-tags",
                    title="Latin Song",
                    artist="Latin Artist",
                    album_artist="Latin Artist",
                    evidence=smo.local_credit_evidence(
                        "Latin Artist", "Latin Artist", False, smo.DEFAULT_CONFIG
                    ),
                ),
            )
        )
        for index in range(20):
            artist = f"هنرمند {index}"
            plans.append(
                smo.TrackPlan(
                    source=Path(f"rtl-{index}.mp3"),
                    audio=smo.AudioInfo(tags=smo.Tags(artist=artist)),
                    candidate=smo.Candidate(
                        source="existing-tags",
                        title=f"Song {index}",
                        artist=artist,
                        album_artist=artist,
                        evidence=smo.local_credit_evidence(
                            artist, artist, False, smo.DEFAULT_CONFIG
                        ),
                    ),
                )
            )

        config = dict(smo.DEFAULT_CONFIG)
        config["artist_identity_time_budget_seconds"] = 0.12
        config["artist_identity_lookup_limit"] = 30

        client = SlowIdentityClient()
        started = time.monotonic()
        smo.resolve_artist_identities_online(plans, client, config, offline=False)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.35)
        self.assertLessEqual(len(client.queries), 4)
        self.assertLess(len(client.queries), 20)

    def test_flat_artist_layout_omits_album_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artist, album, filename, target = smo.fit_target_path(
                root,
                "Artist",
                "",
                "Song - Artist.mp3",
                240,
            )
            self.assertEqual(artist, "Artist")
            self.assertEqual(album, "")
            self.assertEqual(filename, "Song - Artist.mp3")
            self.assertEqual(target, root / "Artist" / "Song - Artist.mp3")

    def test_album_subfolder_setting_defaults_to_album_folders(self):
        self.assertTrue(smo.DEFAULT_CONFIG["album_subfolders_enabled"])
        self.assertEqual(
            smo.destination_album_folder("Album", smo.DEFAULT_CONFIG),
            "Album",
        )
        flat_config = dict(smo.DEFAULT_CONFIG)
        flat_config["album_subfolders_enabled"] = False
        self.assertEqual(
            smo.destination_album_folder("Album", flat_config),
            "",
        )

    def test_legacy_artist_subfolder_setting_is_still_supported(self):
        legacy_config = {"artist_subfolders_enabled": False}
        self.assertEqual(
            smo.destination_album_folder("Album", legacy_config),
            "",
        )

    def test_artist_folder_defaults_to_human_readable_display_name(self):
        self.assertEqual(
            smo.format_artist_folder_name(
                "alireza_ghorbani",
                False,
                smo.DEFAULT_CONFIG,
            ),
            "Alireza Ghorbani",
        )
        self.assertEqual(
            smo.format_artist_folder_name(
                "علیرضا قربانی",
                True,
                smo.DEFAULT_CONFIG,
            ),
            "علیرضا قربانی",
        )

    def test_artist_folder_can_still_use_configured_snake_case(self):
        config = dict(smo.DEFAULT_CONFIG)
        config["artist_folder_name_style"] = "snake_case"
        self.assertEqual(
            smo.format_artist_folder_name("Alireza Ghorbani", False, config),
            "alireza_ghorbani",
        )

    def test_filename_credit_keeps_guests_in_parentheses(self):
        candidate = smo.Candidate(
            source="spotify",
            title="Example Song",
            artist="Alireza Ghorbani, Guest One, Guest Two",
            album_artist="Alireza Ghorbani",
            evidence={
                "track_artist_entities": [
                    "Alireza Ghorbani",
                    "Guest One",
                    "Guest Two",
                ],
                "track_artist_keys": [
                    "spotify:alireza",
                    "spotify:guest1",
                    "spotify:guest2",
                ],
                "track_artist_atomic": False,
                "album_artist_entities": ["Alireza Ghorbani"],
                "album_artist_keys": ["spotify:alireza"],
                "album_artist_atomic": True,
            },
        )
        plan = smo.TrackPlan(
            source=Path("collaboration.mp3"),
            audio=smo.AudioInfo(
                tags=smo.Tags(artist="Alireza Ghorbani feat. Guest One & Guest Two")
            ),
            candidate=candidate,
        )
        profile = smo.build_profile_from_plans([plan], False, smo.DEFAULT_CONFIG)
        credit = smo.output_artist_credit(
            candidate,
            plan.audio.tags,
            profile,
            False,
            smo.DEFAULT_CONFIG,
        )
        self.assertEqual(
            credit,
            "Alireza Ghorbani (Guest One x Guest Two)",
        )
        self.assertEqual(
            smo.build_filename(candidate.title, credit, False),
            "Example Song - Alireza Ghorbani (Guest One x Guest Two).mp3",
        )

    def test_filename_credit_reorders_album_owner_as_primary(self):
        candidate = smo.Candidate(
            source="spotify",
            title="Duet",
            artist="Guest Singer, Main Singer",
            album_artist="Main Singer",
            evidence={
                "track_artist_entities": ["Guest Singer", "Main Singer"],
                "track_artist_keys": ["spotify:guest", "spotify:main"],
                "track_artist_atomic": False,
                "album_artist_entities": ["Main Singer"],
                "album_artist_keys": ["spotify:main"],
                "album_artist_atomic": True,
            },
        )
        plan = smo.TrackPlan(
            source=Path("duet.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Main Singer")),
            candidate=candidate,
        )
        profile = smo.build_profile_from_plans([plan], False, smo.DEFAULT_CONFIG)
        self.assertEqual(
            smo.output_artist_credit(
                candidate,
                plan.audio.tags,
                profile,
                False,
                smo.DEFAULT_CONFIG,
            ),
            "Main Singer (Guest Singer)",
        )

    def test_provider_atomic_group_is_not_split_in_filename(self):
        candidate = smo.Candidate(
            source="musicbrainz",
            title="Group Song",
            artist="Alpha & Beta",
            album_artist="Alpha & Beta",
            evidence={
                "track_artist_entities": ["Alpha & Beta"],
                "track_artist_keys": ["mb:group"],
                "track_artist_atomic": True,
                "album_artist_entities": ["Alpha & Beta"],
                "album_artist_keys": ["mb:group"],
                "album_artist_atomic": True,
            },
        )
        plan = smo.TrackPlan(
            source=Path("group.mp3"),
            audio=smo.AudioInfo(tags=smo.Tags(artist="Alpha & Beta")),
            candidate=candidate,
        )
        profile = smo.build_profile_from_plans([plan], False, smo.DEFAULT_CONFIG)
        self.assertEqual(
            smo.output_artist_credit(
                candidate,
                plan.audio.tags,
                profile,
                False,
                smo.DEFAULT_CONFIG,
            ),
            "Alpha & Beta",
        )

    def test_uncertain_catalog_result_can_fall_back_to_acoustid(self):
        audio = smo.AudioInfo(
            tags=smo.Tags(
                title="Known Song",
                artist="Known Artist",
                album="Known Album",
            ),
            duration_seconds=210.0,
        )
        fingerprint_candidate = smo.Candidate(
            source="acoustid",
            title="Fingerprint Song",
            artist="Fingerprint Artist",
            album="Fingerprint Album",
            album_artist="Fingerprint Artist",
            confidence=95.0,
            title_similarity=100.0,
            artist_similarity=100.0,
            evidence={"fingerprint_score": 0.95},
        )
        config = dict(smo.DEFAULT_CONFIG)
        config["verify_existing_tags_online"] = True
        config["acoustid_api_key"] = "test-key"

        with (
            patch.object(smo, "identify_online", return_value=(None, [])),
            patch.object(
                smo,
                "identify_by_fingerprint",
                return_value=(fingerprint_candidate, []),
            ) as fingerprint_lookup,
        ):
            candidate, errors = smo.determine_candidate(
                source=Path("Known Song - Known Artist.mp3"),
                audio=audio,
                default_artist="",
                normalize_persian=False,
                config=config,
                client=object(),
                min_confidence=85.0,
                verify_online=True,
                offline=False,
                unknown_artist_folder="_Unknown Artist",
                fpcalc_path=Path("fpcalc.exe"),
            )

        self.assertEqual(errors, [])
        self.assertEqual(candidate.source, "acoustid")
        self.assertEqual(candidate.title, "Fingerprint Song")
        fingerprint_lookup.assert_called_once()

    def test_low_acoustid_score_is_rejected(self):
        class FingerprintClient:
            def acoustid_lookup(self, api_key, duration, fingerprint):
                return {
                    "results": [{
                        "score": 0.40,
                        "recordings": [{
                            "id": "recording-id",
                            "title": "Wrong Song",
                            "artists": [{"id": "artist-id", "name": "Wrong Artist"}],
                        }],
                    }]
                }

            def musicbrainz_recording(self, recording_id):
                return None

        config = dict(smo.DEFAULT_CONFIG)
        config["acoustid_api_key"] = "test-key"
        with patch.object(smo, "audio_fingerprint", return_value=(200, "fingerprint")):
            candidate, errors = smo.identify_by_fingerprint(
                Path("song.mp3"),
                Path("fpcalc.exe"),
                FingerprintClient(),
                config,
            )
        self.assertIsNone(candidate)
        self.assertTrue(any("below" in error for error in errors))

    def test_similar_transliteration_variants_share_one_artist_folder(self):
        config = dict(smo.DEFAULT_CONFIG)
        profile = smo.LibraryProfile(config)
        for name in ["Hassan Shamaeezadeh", "Hassan Shamizadeh", "Hassan Shamaeezadeh"]:
            profile.register_entity(smo.ArtistRef(name, f"name:{smo.comparison_text(name)}", False))
        first = profile.canonical_artist("Hassan Shamaeezadeh")
        second = profile.canonical_artist("Hassan Shamizadeh")
        self.assertEqual(first, second)

    def test_registry_alias_collapses_persian_and_latin_artist_names(self):
        config = dict(smo.DEFAULT_CONFIG)
        config["_artist_registry"] = {
            "artists_by_id": {
                "ir.alireza-ghorbani": smo.RegistryArtist(
                    id="ir.alireza-ghorbani",
                    canonical_name="Alireza Ghorbani",
                    preferred_folder_name="Alireza Ghorbani",
                    native_name="علیرضا قربانی",
                    roles=("singer",),
                    aliases=("علیرضا قربانی", "Alireza Qorbani", "alireza_ghorbani"),
                )
            },
            "aliases": {
                smo.comparison_text("علیرضا قربانی"): "ir.alireza-ghorbani",
                smo.comparison_text("Alireza Qorbani"): "ir.alireza-ghorbani",
                smo.comparison_text("alireza_ghorbani"): "ir.alireza-ghorbani",
            },
            "provider_ids": {},
        }
        refs = smo.artist_refs_from_names(["علیرضا قربانی", "Alireza Qorbani"], config=config)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].key, "registry:ir.alireza-ghorbani")
        profile = smo.LibraryProfile(config)
        profile.register_entity(refs[0])
        self.assertEqual(
            profile.canonical_artist("Alireza Qorbani", refs[0].key),
            "Alireza Ghorbani",
        )

    def test_local_track_registry_is_used_as_free_offline_fallback(self):
        artist = smo.RegistryArtist(
            id="ir.alireza-ghorbani",
            canonical_name="Alireza Ghorbani",
            preferred_folder_name="Alireza Ghorbani",
            aliases=("alireza_ghorbani",),
        )
        track = smo.RegistryTrack(
            id="ir.demo",
            canonical_title="Demo Track",
            artist_ids=("ir.alireza-ghorbani",),
            album="Demo Album",
            aliases=(("demo track", "alireza_ghorbani"),),
        )
        config = dict(smo.DEFAULT_CONFIG)
        config["_artist_registry"] = {
            "artists_by_id": {artist.id: artist},
            "aliases": {
                smo.comparison_text("alireza_ghorbani"): artist.id,
                smo.comparison_text("Alireza Ghorbani"): artist.id,
            },
            "provider_ids": {},
        }
        config["_track_registry"] = {
            "tracks_by_key": {(smo.comparison_text("demo track"), artist.id): track},
            "tracks_by_isrc": {},
        }
        candidate = smo.local_registry_candidate(
            smo.AudioInfo(tags=smo.Tags()),
            [smo.Seed(title="demo track", artist="alireza_ghorbani", source="filename")],
            False,
            config,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.source, "local-registry")
        self.assertEqual(candidate.artist, "Alireza Ghorbani")
        self.assertEqual(candidate.album, "Demo Album")

    def test_explicit_composer_cannot_replace_different_local_performer(self):
        config = dict(smo.DEFAULT_CONFIG)
        profile = smo.LibraryProfile(config)
        candidate = smo.Candidate(
            source="musicbrainz",
            title="Song",
            artist="Known Composer",
            evidence={
                "track_artist_entities": ["Known Composer"],
                "track_artist_keys": ["mb:composer"],
                "track_artist_atomic": True,
            },
        )
        old_tags = smo.Tags(
            artist="Actual Singer",
            composer="Known Composer",
        )
        chosen = smo.resolve_primary_artist_ref(candidate, old_tags, profile, False, config)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.name, "Actual Singer")

    def test_album_trust_gate_puts_one_track_title_releases_in_singles(self):
        config = dict(smo.DEFAULT_CONFIG)
        candidate = smo.Candidate(
            source="apple",
            title="Darya Kojaast",
            artist="Chaartaar",
            album="Daryaa Kojast",
            album_artist="Chaartaar",
            evidence={"release_primary_type": "single", "release_track_count": 1},
        )
        raw_album = smo.album_folder_for(
            candidate,
            smo.Tags(),
            "Chaartaar",
            smo.LibraryProfile(config),
            False,
            config,
        )
        final_album = smo.reliable_album_folder_for(
            raw_album, candidate, smo.Tags(), 1, False, config
        )
        self.assertEqual(final_album, "Singles")
        self.assertEqual(candidate.evidence["album_folder_reason"], "provider-release-type-single")

    def test_album_trust_gate_keeps_multi_track_album_folder(self):
        config = dict(smo.DEFAULT_CONFIG)
        candidate = smo.Candidate(
            source="existing-tags",
            title="Track One",
            artist="Artist",
            album="Real Album",
            album_artist="Artist",
        )
        raw_album = smo.album_folder_for(
            candidate,
            smo.Tags(album="Real Album"),
            "Artist",
            smo.LibraryProfile(config),
            False,
            config,
        )
        final_album = smo.reliable_album_folder_for(
            raw_album, candidate, smo.Tags(album="Real Album"), 3, False, config
        )
        self.assertEqual(final_album, "Real Album")
        self.assertEqual(candidate.evidence["album_folder_reason"], "library-multi-track:3")

    def test_chaartaar_registry_seed_maps_tracks_to_canonical_album_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Load the real bundled reference files through the project loader.
            config = dict(smo.DEFAULT_CONFIG)
            smo.load_local_registries(ROOT, config)
            candidate = smo.local_registry_candidate(
                smo.AudioInfo(tags=smo.Tags()),
                [smo.Seed(title="Daryaa Kojast", artist="Chaartaar", source="filename")],
                False,
                config,
            )
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.artist, "Chaartaar")
            self.assertEqual(candidate.album, "Darya Kojaast")

    def test_spotify_fallback_only_waits_until_free_sources_fail(self):
        class MemoryCache:
            def __init__(self):
                self.value = None

            def get_identification(self, key, max_age_days):
                return None

            def set_identification(self, key, payload):
                self.value = payload

        class FallbackClient:
            apple_country = "US"
            cache = MemoryCache()

            def spotify_enabled(self):
                return True

            def musicbrainz_search(self, title, artist, isrc=None):
                return []

            def apple_search(self, title, artist):
                return []

            def spotify_search(self, title, artist, isrc=None, album=None, limit=10):
                return [{
                    "id": "spotify-track-id",
                    "name": title,
                    "artists": [{"id": "spotify-artist-id", "name": artist}],
                    "album": {"name": album or "Single"},
                    "external_ids": {"isrc": isrc or ""},
                    "duration_ms": 200000,
                }]

        config = dict(smo.DEFAULT_CONFIG)
        config["spotify_fallback_only"] = True
        config["spotify_min_confidence"] = 90.0
        audio = smo.AudioInfo(tags=smo.Tags(title="Song", artist="Artist"), duration_seconds=200)
        candidate, errors = smo.identify_online(
            audio,
            [smo.Seed(title="Song", artist="Artist", source="test")],
            FallbackClient(),
            config,
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.source, "spotify")
        self.assertTrue(candidate.evidence.get("spotify_fallback_only"))


if __name__ == "__main__":
    unittest.main()
