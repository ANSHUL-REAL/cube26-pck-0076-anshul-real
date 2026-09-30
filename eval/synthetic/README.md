# DISCLOSED synthetic Pack Manager benchmark

**Every image in this directory is AI-generated:** the product reference photos and the box photos. These images belong only to the synthetic evaluation set.

- Image model: OpenAI image generation (the image-generation interface did not expose a more specific model identifier).
- Generation date: 2026-09-30.
- Ground truth: the packing plan written before box-image generation, recorded in this directory's `manifest.csv`.
- Dropped boxes: none.
- Results on this synthetic set must be reported separately from results on the real held-out photo set. Never mix these images with the real photo set.

Generation prompts and attempt counts are recorded in `prompts.csv`.

**Photos in this repository.** `boxes/<box>/1.jpg` is the exact JPEG the model was sent for each box: the generated PNG after the app's own photo preparation (upright, resized, re-encoded, metadata removed). Each file's SHA-256 equals `images[].sha256` in that box's records under `results/`, and a test checks this (`tests/test_eval_tools.py`). The generated PNG originals (165 MB, with their embedded metadata) and the reference-photo originals (51 MB) are kept by the author outside the repository. `frozen-test.json` holds the SHA-256 of every original PNG, recorded before the held-out run. So `run_eval.py --split test` can't re-verify the freeze from this repository alone. A re-run on the committed JPEGs needs `--unfrozen`, and is then marked as not held-out.