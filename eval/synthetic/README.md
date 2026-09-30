# DISCLOSED synthetic Pack Manager benchmark

**Every image in this directory is AI-generated:** the product reference photos and the box photos. These images belong only to the synthetic evaluation set.

- Image model: OpenAI image generation (the image-generation interface did not expose a more specific model identifier).
- Generation date: 2026-09-30.
- Ground truth: the packing plan written before box-image generation, recorded in this directory's `manifest.csv`.
- Dropped boxes: none.
- Results on this synthetic set must be reported separately from results on the real held-out photo set. Never mix these images with the real photo set.

The original generated PNGs are retained, including their embedded image metadata. Product reference images are under `reference_originals/`; box images are under `boxes/`. Generation prompts and attempt counts are recorded in `prompts.csv`.