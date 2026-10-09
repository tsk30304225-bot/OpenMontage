# 오후 3시 커피의 시계 — 결정 기록 요약

- 파이프라인: animated-explainer (리서치 → 기획 → 대본 → 장면 → 에셋 → 편집 → 렌더)
- 승인: 기획·대본·장면 계획은 사용자가 이 세션에서 직접 승인. 에셋 게이트는 사용자의 "남은 단계 위임"으로 진행
  (decision_log 스키마에 `approval_policy` 카테고리가 없어 체크포인트 metadata에 기록)
- 콘셉트: c1 "오후 3시 커피의 시계" (c2의 아데노신 설명을 중간 비트로 병합), 1920x1080
- 런타임: Remotion. timeline_rail 범용 렌더러와 karaoke 어절 자막 지원.
  HyperFrames는 karaoke 자막 미지원·timeline_rail 범용 렌더러 없음으로 제외, FFmpeg는 모션 그래픽 불가로 제외
- 구성 방식: templated (테스트 목적)
- 내레이션: minimax_tts speech-2.8-hd / Korean_LonelyWarrior / language_boost Korean, 전체 대본 1회 호출,
  35.86초, $0.026
- 자막: MiniMax word_timestamps(어절) → alignment.json → PhraseCaptions(karaoke) 번인.
  문장 경계에서 붙은 2개 토큰(했습니다.카페인은 / 것.카페인의)을 프로젝트 데이터에서 분리
- B-roll: Pexels 6683374 (라테 붓기, 원래 고른 차 영상 교체), Pixabay 58580 (도시 노을 타임랩스, 세로 CG 교체),
  Pexels 7658235 (커피잔 내려놓기)
- 음악: Pixabay "Calm Lofi"(The_Mountain). audio_mixer duck(-14 dB 상당, attack 150 ms / release 600 ms)로
  내레이션과 사전 믹스 후 video_compose audio_path로 mux. Remotion Explainer에 덕킹 기능이 없어서임
- 마무리: Remotion이 마지막 컷 뒤에 붙이는 1초 빈 구간(배경색이 비침)을 스트림 복사로 잘라냄
- 최종: 38.07초, 18.7 MB, h264 + aac, -14.3 LUFS / TP -1.9 dBTP
- 검수: final_review 통과, direction_qa 치명 오류 0건(경고 1건: 45분 MEASURE 변화 작음), 검은 화면 없음,
  ASR(whisper base) 0.0–35.4초 전체 내레이션 확인
- 총비용: $0.026 (MiniMax TTS)

## v2 — Remotion atelier + HyperFrames (사용자 요청)
- composition_mode: templated → atelier. 승인 런타임: remotion + hyperframes. 사용자가 직접 요청
- 아트 디렉션(art-direction.md): 실제 시계판의 3시~9시 구간을 커피잔 테두리처럼 그리고, 흡수(크레마 골드)·졸음 신호
  차단(앰버)·남은 절반(점선)을 채움. sc5는 밤 색으로 바뀌며 바늘이 20:00까지 돌아감. Hahmlet(세리프) + Noto Sans KR
- 장면별 주 피사체를 서로 다르게 구성:
  - sc1 라테 실사 + "3:00" 타이틀
  - sc2 다이얼 확대 + "45분" 카운트
  - sc3 다이얼 전체 + "피로"가 베일에 가려짐
  - sc4 HyperFrames 키네틱 타이포 "퇴장은, 느리다."(색수차 슬램 + 잔상)
  - sc5 밤 다이얼 + 바늘 + 50%
  - sc6 실사 + "마지막 잔은, 이른 오후에."
- 그래픽 변화 5개는 direction 훅으로 구현됨(트레이스 5/5). 그래픽 변화 시간을 0.9~1.6초로 늘림(앵커 시작점은 그대로)
- 결과: 38.0초, 15.6MB, -14.3 LUFS. final_review 통과, direction_qa 치명 오류 0건, 검은 화면 없음
- 추가 비용: 없음(TTS 재사용)
