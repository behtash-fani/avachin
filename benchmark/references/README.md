# Local benchmark references

Place trusted source audio under `benchmark/references/local/`. This directory is ignored by Git.

Each file must represent one verified Recording. Keep Studio, Live, Remix, and Remaster versions as separate references with distinct stable identifiers, even when artist and title text are identical.

The benchmark stores paths and identifiers in the machine-local `benchmark/manifest.json`; it never copies audio into reports or the repository.
