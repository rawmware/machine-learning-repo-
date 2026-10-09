"""Restricted loopback Ollama HTTP client."""
from __future__ import annotations
import http.client, json, socket, time
from urllib.parse import urlsplit

class OllamaError(RuntimeError):
    def __init__(self, message, code="ollama_error"): super().__init__(message); self.code=code

class OllamaClient:
    def __init__(self, base_url="http://127.0.0.1:11434", timeout=90, max_response=2_000_000):
        u=urlsplit(base_url)
        if u.scheme!="http" or u.hostname not in {"127.0.0.1","localhost","::1"} or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
            raise ValueError("Ollama URL must be plain HTTP on loopback only")
        if not 0.1 <= timeout <= 600: raise ValueError("timeout must be 0.1..600 seconds")
        self.host=u.hostname; self.port=u.port or 80; self.timeout=timeout; self.max_response=max_response
    def _request(self,path,payload=None):
        conn=http.client.HTTPConnection(self.host,self.port,timeout=self.timeout)
        data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode("utf-8")
        try:
            conn.request("GET" if payload is None else "POST",path,body=data,headers={"Content-Type":"application/json","Accept":"application/json"})
            res=conn.getresponse()
            if res.status<200 or res.status>=300:
                body=res.read(min(4096,self.max_response)).decode("utf-8","replace")
                raise OllamaError(f"Ollama HTTP {res.status}: {body[:800]}","http_error")
            raw=res.read(self.max_response+1)
            if len(raw)>self.max_response: raise OllamaError("Ollama response exceeds size limit","response_too_large")
            try: value=json.loads(raw)
            except (UnicodeError,json.JSONDecodeError) as e: raise OllamaError("Ollama returned malformed JSON","invalid_json") from e
            if not isinstance(value,dict) or not value: raise OllamaError("Ollama returned empty or non-object JSON","invalid_json")
            return value
        except (socket.timeout,TimeoutError) as e: raise OllamaError("Ollama request timed out","timeout") from e
        except OSError as e: raise OllamaError(f"Cannot reach loopback Ollama: {e}","connection_error") from e
        finally: conn.close()
    def tags(self): return self._request("/api/tags")
    def show(self,model): return self._request("/api/show",{"model":model})
    def chat(self,model,messages,*,schema=None,num_ctx=8192,num_predict=768):
        fmt=schema if schema is not None else "json"
        return self._request("/api/chat",{"model":model,"messages":messages,"stream":False,"format":fmt,"options":{"num_ctx":num_ctx,"num_predict":num_predict}})
