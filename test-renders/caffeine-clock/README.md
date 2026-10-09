# Test render — "오후 3시 커피의 시계"

OpenMontage animated-explainer 파이프라인 종단 테스트 결과물입니다(MiniMax TTS 검증 포함).

- `caffeine-clock.mp4` — 최종본(v2). Remotion atelier + HyperFrames sc4, 38초, 1920x1080, h264 + aac, -14.3 LUFS
- `subtitles.json` — 어절 단위 정렬(MiniMax word_timestamps 기반, 78어절)
- `subtitles.minimax_raw.json` — MiniMax T2A v2가 반환한 원본 자막 JSON
- `decision_log_summary.md` — 단계별 결정 요약(v1 templated → v2 atelier)
- `source/` — 참고용 작성 소스: Remotion `Composition.tsx`, `art-direction.md`, HyperFrames `hf-sc4/index.html`.
  실행 가능한 프로젝트가 아니며, 원본 작업 공간은 git에서 제외된 `projects/caffeine-clock/`입니다.

소스 영상: Pexels 6683374, Pexels 7658235, Pixabay 58580. 음악: Pixabay "Calm Lofi"(The_Mountain).
비용: MiniMax TTS 1회 $0.026.
