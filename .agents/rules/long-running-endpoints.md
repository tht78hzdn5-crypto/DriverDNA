# Long-Running Endpoints & SSE Streaming

When implementing or modifying API endpoints that perform long-running tasks (e.g., batch file processing, third-party network syncs, or anything that might exceed Cloudflare's 100-second proxy timeout):

1. **Never use blocking JSON responses** for tasks that scale with input size.
2. **Use Server-Sent Events (SSE)**: Return a FastAPI `StreamingResponse` with `media_type="text/event-stream"`.
3. **Threading Model for Sync Tasks**:
   - If the underlying work is synchronous, run it in a daemon `threading.Thread`.
   - Pass an `on_progress` callback to the worker that puts events into a `queue.Queue`.
   - The route's generator should yield events from `queue.get()` until a `complete` or `error` event is received.
   - **Database Warning**: Do not pass request-scoped SQLAlchemy sessions (`Depends(get_db)`) directly into background threads, as this can cause thread-safety and session-closure issues.
4. **Event Shape**:
   - Yield JSON-encoded strings formatted as `data: {"type": "...", ...}\n\n`.
   - Always emit a final `{"type": "complete", ...}` event containing the final state, or an `{"type": "error", "detail": "..."}` event if it fails.
5. **Frontend**:
   - Consume these endpoints using the `streamChat` / `streamUpload` pattern in `api.js`.
   - Maintain incremental UI state (e.g., progress bars and partial result cards) as events arrive.
