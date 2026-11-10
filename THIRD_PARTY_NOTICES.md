# Third-party notices

## Distribution scope

The repository is distributed as a pinned source plugin under [MIT](LICENSE),
except for the attributed vendored material below. Keep these notices with source
archives. Models, voices, browser binaries and datasets are not bundled; explicit
setup downloads the pinned assets to local caches.

Direct Python requirements are in [pyproject.toml](pyproject.toml). Their published
licences include BSD-3-Clause (websockets, NumPy), MIT (faster-whisper, sounddevice,
PyObjC), Apache-2.0 (parakeet-mlx, huggingface_hub), and MIT OR Apache-2.0 (ptts).
The installation record checks resolved metadata, not every transitive source
file or platform wheel. A source beta is not legal clearance for redistributing
a native-app bundle, model mirror, generated voice recording or all dependencies.
See [release scope and remaining legal/distribution gates](docs/RELEASE_READINESS.md).

## Parakeet speech recognition

- Preferred macOS model: **Parakeet TDT 0.6B v2**, NVIDIA's
  [original v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2/blob/ae9ad07059c7c739ffaf932226a8fe64ae2620b0/README.md),
  converted to CoreML by **FluidInference**, **CC-BY-4.0** per the
  [pinned conversion card](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v2-coreml/blob/ee09c569f73759e6d44c9bd16766f477b2b36d39/README.md).
  The downloaded conversion is unmodified; FluidInference publishes it.
  NVIDIA endorsement is not established.
- macOS fallback: **mlx-community's MLX conversion** of NVIDIA Parakeet v2,
  **CC-BY-4.0**, [revision and conversion attribution](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2/blob/8ae155301e23d820d82aa60d24817c900e69e487/README.md).
  The [parakeet-mlx runtime](https://github.com/senstella/parakeet-mlx) is Apache-2.0.
- [CC-BY-4.0 terms](https://creativecommons.org/licenses/by/4.0/).
  No training-data licence or catalog acceptance is established by these weight terms.
- CoreML **v3 is unsupported**, not the default. Its
  [card at `7dd20fe6b1797d35f5e3307e8b1732d9a178edfe`](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v3-coreml/blob/7dd20fe6b1797d35f5e3307e8b1732d9a178edfe/README.md)
  contradicts itself: CC-BY-4.0 frontmatter, Apache 2.0 body. These notices do not
  resolve that contradiction or infer weight terms from the FluidAudio code licence.

`asr/parakeet_coreml.py` vendors silicon-asr 0.1.0's runner, windowing and types,
adapted for pyobjc CoreML, decoded PCM input and pinned/verified v2-only loading.
[Upstream MIT licence](https://github.com/WT-MM/silicon-asr/blob/e8f2e021007eab99031183bed484a82bdfc22a28/LICENSE):

```text
MIT License

Copyright (c) 2026 WT-MM

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## faster-whisper English models

- [SYSTRAN faster-whisper runtime](https://github.com/SYSTRAN/faster-whisper): MIT.
- SYSTRAN's conversions of OpenAI Whisper:
  [base.en](https://huggingface.co/Systran/faster-whisper-base.en/blob/3d3d5dee26484f91867d81cb899cfcf72b96be6c/README.md) and
  [tiny.en](https://huggingface.co/Systran/faster-whisper-tiny.en/blob/0d3d19a32d3338f10357c0889762bd8d64bbdeba/README.md),
  MIT per their cards. The selected repository tokenizer is mandatory and verified;
  no separately downloaded OpenAI tokenizer is used. Tokenizer-specific legal
  terms beyond the conversion cards were not independently established.

Recognition and Phonon file revisions and SHA-256 expectations are in
[`assets.json`](assets.json). Weight/embedding hashes derive from immutable
publisher LFS metadata, not a claim that this release audit downloaded those weights.
CoreML/MLX official-distribution acceptance under the Hermes catalog remains a
maintainer decision; pinning alone is not catalog approval.

## Gradium Phonon read-aloud

- Runtime: [`ptts` 0.6.0 / xn-ptts](https://github.com/gradium-ai/xn-ptts),
  Laurent Mazare and Gradium; **MIT OR Apache-2.0**. Its wheel includes both
  `LICENSE-MIT` and `LICENSE-APACHE`; retain these when redistributing the runtime.
- [Phonon-31M English weights, tokenizer and bundled voice](https://huggingface.co/gradium/phonon-31m-en/tree/8c64b55ec301728e2d1695bfea87a08a267d0c2d),
  Gradium, **Apache-2.0**, revision `8c64b55ec301728e2d1695bfea87a08a267d0c2d`.
  Only the q8 31M checkpoint is used, not the CC-BY-NC 40M siblings.
- [Phonon catalogue voices](https://huggingface.co/gradium/phonon-voices/tree/0ee17205f254b5abc43b266c8a0f215565c352f7),
  Gradium, **Apache-2.0**, revision `0ee17205f254b5abc43b266c8a0f215565c352f7`.
  Default: Russell, voice ID `_6Aslh2DxfmnRLmP`.

Setup downloads unmodified assets and their model cards outside this repository.
The Apache-2.0 licence text below also applies to these assets. No model weights,
voice embeddings, training data or generated speech are bundled in this repository.
The emergency Apple `say` fallback uses installed system voices; its generated
audio is not established as licensed for publication in the submission video.

## MediaPipe Tasks Vision and Face Landmarker

Copyright Google LLC and the MediaPipe authors. Apache License, Version 2.0.
The runtime and model are downloaded unmodified, outside this repository.

- Runtime: [`@mediapipe/tasks-vision` 0.10.32](https://registry.npmjs.org/@mediapipe/tasks-vision/0.10.32).
  Official npm tarball: `https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.32.tgz`
  SHA-256: `b362a2b56aafcce7857047c25dc8fd69612fd8e75018e264717d24290e7815c1`.
- Weights: [Face Landmarker float16, version 1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task).
  SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
- [Face Mesh V2 model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf)
  explicitly licenses the 478-landmark weights under Apache-2.0.
- [Blendshape model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf)
  also states Apache-2.0; blendshape output is not enabled here.
- [BlazeFace short-range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf)
  licenses the detector weights under Apache-2.0 and describes consented AR-app
  training images, without separate downloadable dataset terms.
- Training-image dataset names and separate dataset licences are not published
  in the Face Mesh V2 card. Do not claim that those data are Apache-licensed.
  The gaze regressor uses only the user's own local nine-point calibration.

`webcam.prepare_assets` checks both hashes before use and re-extracts the verified
JS/WASM bytes on startup. No GazeFollower, GazeFollower2, WebEyeTrack, EyeTrax or
Glance code or gaze weights are included in this implementation.

## Test portrait (not model training data)

NASA image S69-31741, official portrait of Neil Armstrong, credit NASA.
[Image source](https://www.nasa.gov/image-article/official-portrait-of-neil-armstrong/).
[Usage guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/).
US-government photograph, used only as a public-domain local fake-camera fixture;
no endorsement or human gaze accuracy is implied. The test crops/translates it.

Downloaded image SHA-256:
`1cb000ea1005dc2b63bc0593e86a371b95105a9e1c989876b7dbd1874837714c`.
Neither the portrait nor generated video is committed.

## MediaPipe upstream licence

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

===========================================================================
For files under tasks/cc/text/language_detector/custom_ops/utils/utf/
===========================================================================
/*
 * The authors of this software are Rob Pike and Ken Thompson.
 *              Copyright (c) 2002 by Lucent Technologies.
 * Permission to use, copy, modify, and distribute this software for any
 * purpose without fee is hereby granted, provided that this entire notice
 * is included in all copies of any software which is or includes a copy
 * or modification of this software and in all copies of the supporting
 * documentation for such software.
 * THIS SOFTWARE IS BEING PROVIDED "AS IS", WITHOUT ANY EXPRESS OR IMPLIED
 * WARRANTY.  IN PARTICULAR, NEITHER THE AUTHORS NOR LUCENT TECHNOLOGIES MAKE ANY
 * REPRESENTATION OR WARRANTY OF ANY KIND CONCERNING THE MERCHANTABILITY
 * OF THIS SOFTWARE OR ITS FITNESS FOR ANY PARTICULAR PURPOSE.
 */
