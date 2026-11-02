# Core v3 (v3.1): amendment 2, the adapter hash and the pre-test checks

Dated 2026-11-01, committed before the first test run. It adds the adapter's hash and reports the checks that amendment 1 required; it changes no task, arm, measure or rule.

- **Adapter.** `Muse-Glimmer-30B-v3-self`, file `glimmer-v3-self.gguf`, sha256 `97c4b9e0d57c84f67125921c9b891a16f1aab68c18a1df844cd91dcf8944827d` (649,235,584 bytes). The Strix router registers it as `Muse-Glimmer-30B-v3-self`; a greedy 150-token completion of a fixed prompt differs from plain's [measured].
- **Training.** 278 rows, 2 epochs, the held-out loss evaluated at the end of each epoch. The best held-out loss, 0.352, was at step 278 (the end of the first epoch), so the first-epoch checkpoint is the adapter [measured].
- **Reasoning-collapse check.** On 3 train-task prompts, greedy: plain's reasoning was 65, 65 and 521 characters (median 65); the adapter's was 33, 33 and 48 (median 33), a ratio of 0.51 against the 0.50 bar, with 3 of 3 valid actions in both. The check passes narrowly; the adapter writes noticeably shorter reasoning, which the test's secondary reports [measured].
- **5080.** The same file is served there with per-request LoRA scales and a fingerprint probe before each block, as amendment 1 says; if its greedy output does not differ from plain's, or the file hash differs, the 5080 takes no block [established].
