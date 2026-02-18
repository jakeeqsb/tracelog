# TraceLog

> **AI-Native Context Logging for Python**  
> "Don't just log errors. Log the *process* that led to them."

## 🚀 Introduction

**TraceLog**는 LLM 기반의 디버깅을 위해 설계된 **차세대 Python 로깅 SDK**입니다.  
기존 로거(`logging` module)와 완벽하게 통합되면서도, 에러 발생 시점의 **실행 흐름(Execution Context)을 고해상도로 캡처**합니다.

평소에는 조용하다가, 문제가 터졌을 때만 **Trace-DSL** 형태로 상세한 리포트를 제공하여 AI가 단 1초 만에 원인을 분석할 수 있게 돕습니다.

---

## ✨ Key Features

- **🔎 Auto-Tracing**: `@trace` 데코레이터 하나로 함수 진입, 종료, 인자값, 리턴값을 자동 추적.
- **🤝 Delegation Pattern**: 기존 `logging` 설정을 건드리지 않고, TraceLog를 덧씌워(Wrap) 즉시 도입 가능.
- **💾 Smart Buffering**: 메모리 내 `RingBuffer`에 최근 실행 흐름만 저장하여 성능 저하 최소화.
- **⚡️ Instant Dump**: 에러(`ERROR` level) 발생 시, 버퍼에 담긴 실행 궤적을 즉시 덤프.

---

## 🛠 Project Structure

- `tracelog/`: 핵심 SDK 소스 코드
- `examples/`: 사용 예제
- `docs/`: 상세 설계 문서
