import { useState, useEffect } from "react";
import { streamGet } from "./api.js";

// Module-level cache — shared across all consumers. Survives component
// unmounts but not page reloads (which is correct: a fresh page load
// should always re-compute).
let _cache = { payload: null, error: null, promise: null, generation: 0, controller: null };

window.addEventListener("driverdna:unauthenticated", () => invalidateDriverCache());

export function invalidateDriverCache() {
  if (_cache.controller) {
    _cache.controller.abort();
  }
  _cache = {
    payload: null,
    error: null,
    promise: null,
    generation: _cache.generation + 1,
    controller: null
  };
  window.dispatchEvent(new CustomEvent("driverdna:driver_invalidated"));
}

export function useDriverPayload() {
  const [generation, setGeneration] = useState(_cache.generation);
  const [state, setState] = useState({
    driver: _cache.payload,
    driverError: _cache.error,
    rollupProgress: null,
  });

  // Track cache generation changes
  useEffect(() => {
    const handleInvalidate = () => {
      setGeneration(_cache.generation);
    };
    window.addEventListener("driverdna:driver_invalidated", handleInvalidate);
    
    // Also check on mount/update just in case
    if (generation !== _cache.generation) {
      setGeneration(_cache.generation);
    }
    
    return () => window.removeEventListener("driverdna:driver_invalidated", handleInvalidate);
  }, [generation]);

  useEffect(() => {
    let alive = true;

    if (_cache.payload) {
      setState({ driver: _cache.payload, driverError: null, rollupProgress: null });
    } else if (_cache.error) {
      setState({ driver: null, driverError: _cache.error, rollupProgress: null });
    } else {
      if (!_cache.promise) {
        _cache.controller = new AbortController();
        _cache.promise = streamGet("/api/driver", (event) => {
          if (event.type === "progress" || event.type === "progress_phase") {
             window.dispatchEvent(new CustomEvent("driverdna:progress", { detail: event }));
          }
        }, _cache.controller.signal)
          .then((payload) => {
            if (_cache.generation === generation) {
                _cache.payload = payload;
                _cache.promise = null;
                window.dispatchEvent(new CustomEvent("driverdna:driver_loaded", { detail: { payload } }));
            }
          })
          .catch((error) => {
            if (error.name !== 'AbortError' && _cache.generation === generation) {
              _cache.error = String(error.message || error);
              _cache.promise = null;
              window.dispatchEvent(new CustomEvent("driverdna:driver_error", { detail: { error: _cache.error } }));
            }
          });
      }

      const handleLoaded = (e) => alive && setState({ driver: e.detail.payload, driverError: null, rollupProgress: null });
      const handleError = (e) => alive && setState({ driver: null, driverError: e.detail.error, rollupProgress: null });
      const handleProgress = (e) => {
        if (!alive) return;
        const event = e.detail;
        if (event.type === "progress") {
          setState((prev) => ({ ...prev, rollupProgress: event }));
        } else if (event.type === "progress_phase") {
          setState((prev) => ({
            ...prev,
            rollupProgress: {
              ...(prev.rollupProgress || {}),
              cohort: event.phase === "driver_model" ? "computing driver model…" : "computing census…",
            }
          }));
        }
      };

      window.addEventListener("driverdna:driver_loaded", handleLoaded);
      window.addEventListener("driverdna:driver_error", handleError);
      window.addEventListener("driverdna:progress", handleProgress);
      
      return () => {
        alive = false;
        window.removeEventListener("driverdna:driver_loaded", handleLoaded);
        window.removeEventListener("driverdna:driver_error", handleError);
        window.removeEventListener("driverdna:progress", handleProgress);
      };
    }
  }, [generation]);

  return state;
}
