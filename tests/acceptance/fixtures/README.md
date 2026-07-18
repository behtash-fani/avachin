# Acceptance fixtures

Public acceptance scenarios use generated temporary fixtures and mocks.

Machine-local real MP3 fixtures belong in the ignored `local/` directory and should be referenced by a local manifest copy. The runner can verify that protected source files keep the same SHA-256 digest and size before and after each scenario.
