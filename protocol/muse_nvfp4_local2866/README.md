# Muse NVFP4 exact-image TB2.1 local backfill on node 2866

The original NVFP4 model service on allocation 2866 was verified live at `http://10.1.95.27:31320/v1` before reuse. The [ready proof](../../evidence/muse_nvfp4_local2866_ready.json) records the running allocation, service and model ID. A new lane 10 uses CPU allocation 2919 to run only untouched tasks from the frozen round-2/3 completion plan. Its first atomic claim was round-2 batch `b07`.

[`route_future_rounds.py`](route_future_rounds.py) locks and claims one unstarted batch at a time, writing the original configuration hash and an effective configuration that differs only in model endpoint. [`future_round_controller.py`](future_round_controller.py) checks the ready proof, runs the claimed batch, and records terminal task coverage before claiming another. [`harbor_entry.py`](harbor_entry.py) makes the original sequential controller wait for a claimed batch to finish instead of drawing the same tasks again. These are copies of the executed controller files; the base Harbor task runner, exact images, task inputs, and model server are kept in the private run environment and released separately as native I/O archives.

The local lane uses the same original Muse NVFP4 endpoint and generation settings. Original attempts, declared infrastructure replacements, and their native scores remain separate; no best-of selection is made.

The same published controller also supports a second locked slot on allocation 2867. That slot atomically claimed the previously untouched round-2 batch `b08` while slot 0 continued its earlier batch. Both slots retain separate controller locks and the shared per-batch route lock, so each task still has one first draw per round.
