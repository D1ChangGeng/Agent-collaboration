# Linux Artifact component review

Decision: PASS for the sealed component and recorded tests. Domain acceptance
integration and full P1/P2 remain not_run.

## Sealed source

- Commit: `9348c8a597e7b5435119b762d97ee679495545fa`.
- Tree: `a9514f16b58b2f709d1725d2f1e1698ff98aa887`.
- Artifact source SHA-256: `2f3e96a4644d6a01f75a1ff529c08d3056530bb905bce4e13364ef95f6558685`.
- Test source SHA-256: `2050c6901a64b2105291631e95ce3d82f0fe64177bb25ba8fbe70be3a519aade`.
- The commit includes the exact ArtifactRef class required by the store; its
  AST matches the independently exercised candidate. Other receipt/bundle
  model changes remain outside this component.

## Mechanism and review

LocalArtifactStore pins Linux directory descriptors, rejects symlink traversal,
binds a persistent Scope marker and refuses unmarked nonempty roots. Objects
are installed without replacement and verified by actual size and digest.
File ingestion requires explicit authorized source roots. Reads and writes have
a configured limit, defaulting to 16 MiB; files and directories are synchronized
before success. Instances require close or context-manager lifetime management.

Independent review read the frozen source and tests and found no blocking
defects. CAS directories must remain under exclusive control of the service.
Domain/Node still own caller, tenant, Scope and reference authorization.

## Direct verification

Management exported the exact commit into a fresh source snapshot on Linux.
Artifact, existing model and Temporal regressions returned **45 passed, exit 0,
29.95 seconds**. The 34 Artifact scenarios exercised real file operations,
directory replacement and symlink races, growing files, invalid references,
Scope rebinding, corrupt objects and descriptor cleanup. Three serializer
warnings came from intentionally invalid model-copy inputs.

The integrated Windows checkout returned **2 passed, 32 skipped**. These results
verify rejection before filesystem writes when the backend is unavailable;
they do not establish Windows local storage support.

Linux raw output SHA-256:
`ab8246b513aaf7a55a21caa38cb58729ff3242fb61d2c9022083e18ad1d57e19`.
Private evidence is retained under `review-934/`.
The tested environment was Linux 6.11.0-17, Python 3.12.3 and Pydantic 2.13.5.
