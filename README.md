# TraceLog

> **AI-Native Context Logging for Python**  
> "Don't just log errors. Log the *process* that led to them."

## 🚀 Introduction

**TraceLog** is a next-generation Python logging SDK designed for **LLM-based debugging**.  
It seamlessly integrates with the standard `logging` module while capturing high-resolution **execution context** at the moment an error occurs

---

## ✨ Key Features

- **🔎 Auto-Tracing**: Automatically captures function entry, exit, arguments, and return values with a single `@trace` decorator.
- **🤝 Delegation Pattern**: Instantly adopts TraceLog by wrapping your existing logger configuration without breaking changes.
- **💾 Smart Buffering**: Minimizes performance impact by storing only the recent execution flow in an in-memory `RingBuffer`.
- **⚡️ Instant Dump**: Immediately dumps the buffered trajectory when an `ERROR` level log is triggered.
