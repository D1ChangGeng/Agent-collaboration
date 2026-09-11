# Temporal shutdown recovery review

Decision: PASS for R912-09 in the recorded adapter scope. P1/P2 remain not_run.

## Sealed candidate

- Commit: `501bdf7cebcba730c7ffc523189f61911e11cc78`.
- Tree: `e33f61fe03bd9c7bacc0693f85c4875485d28832`.
- Branch: `codex/runtime-p1-invariant-closure`; Push and remote SHA read-back completed.
- Changed files: `runtime/temporal.py` and `runtime_tests/test_temporal_close.py`.
- Temporal source SHA-256: `f7e200e04ea18d6b9b0172bafeb51f02aba077c95990f8e9c45b4af29a4da593`.
- Test source SHA-256: `a7fd3fdec13cc985d1d3edf20105f75af95cfca4af589e289fdc584e05da2625`.

## Independent review

A cancelled close waiter now leaves a retained shared shutdown task and owned
Worker references. Concurrent waiters share shutdown; a shutdown failure keeps
references for explicit retry. After shutdown completes, a terminal run error
propagates while stopped resources are released. The latter case was found by
independent review and corrected before sealing. Reviewer code/memory probes
passed; existing submission, replay and readback method ASTs were unchanged.
LF normalization before commit preserved the reviewed Python AST.

## Direct validation

Management exported the exact commit into a fresh isolated source snapshot and
ran both Temporal test files: **8 passed, exit 0, 29.82 seconds**. This used
Python 3.12.3, Linux 6.11.0-17, Temporal Python SDK 1.32.0 and the existing
isolated acs-p1 Temporal service. Source manifest and raw logs were read back.

The real Worker close-cancellation scenario retained references after waiter
cancellation, completed Worker shutdown, then released references. A fresh
Adapter replayed operation `management-close-ef6bf4973f1349efb1cd989e213ee77f`
using the same Run `01a08f72-79e4-7c0f-ad4d-91d35e3d680d`.
Raw output SHA-256: `c081634afdd70a484fb0d03fd0c5d83cf983e3213ad10dddc1948f018e87d0bc`.
Private evidence is retained under `review-501/`.

Synthetic worker faults establish Python lifecycle behavior. The real service
checks establish adapter shutdown and replay only. They do not establish Core,
Node, Provider-server restart, Harness lifecycle or an integrated P1/P2 Gate.
