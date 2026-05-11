# Integração TikTok API - Guia Completo

## Status: Pronto para Configuração

Seu Uardon está em produção no Railway. Agora vamos integrar TikTok para auto-posting de clips.

---

## Passo 1: Credenciais TikTok

### Opção A: TikTok Business Account (Recomendado)

1. **Acesse TikTok Developer Portal**
   - https://developers.tiktok.com/

2. **Crie uma Application**
   - Login com sua conta TikTok
   - Developer Portal → Create Application
   - Nome: "Uardon Clip Generator"
   - Select products: Video Upload
   - Select platform: Web

3. **Obtenha Credenciais**
   ```
   Client Key (API Key): xxxxxxxxxxxxxxxx
   Client Secret: xxxxxxxxxxxxxxxx
   ```

4. **Configure Redirect URI**
   ```
   Redirect URI: https://web-production-8563b.up.railway.app/api/tiktok-callback
   ```

5. **Solicite Acesso**
   - Submit for review (leva 1-3 dias)
   - Ou use sandbox mode para testes

### Opção B: Usar App Password (Teste Rápido)

Para testes rápidos sem app review:

1. Gere App Password no TikTok
   - Settings → Security → App Passwords
2. Use com sua senha de app

---

## Passo 2: Configurar Variáveis no Railway

No Railway Dashboard:

1. Acesse seu projeto `web`
2. Vá para **Variables**
3. Adicione:

```
TIKTOK_CLIENT_KEY=seu_client_key_aqui
TIKTOK_CLIENT_SECRET=seu_client_secret_aqui
TIKTOK_REDIRECT_URI=https://web-production-8563b.up.railway.app/api/tiktok-callback
TIKTOK_ENABLED=true
```

---

## Passo 3: Arquivo de Configuração TikTok

Criar: `src/tiktok_config.py`

```python
import os
from dataclasses import dataclass

@dataclass
class TikTokConfig:
    """TikTok API Configuration"""
    client_key: str = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("TIKTOK_REDIRECT_URI", "")
    enabled: bool = os.getenv("TIKTOK_ENABLED", "false").lower() == "true"
    
    def is_configured(self) -> bool:
        """Check if TikTok is fully configured"""
        return self.enabled and self.client_key and self.client_secret
    
    @property
    def auth_url(self) -> str:
        """Generate TikTok OAuth URL"""
        if not self.is_configured():
            return ""
        return (
            f"https://www.tiktok.com/v2/oauth/authorize/"
            f"?client_key={self.client_key}"
            f"&redirect_uri={self.redirect_uri}"
            f"&response_type=code"
            f"&scope=video.upload"
        )

tiktok_config = TikTokConfig()
```

---

## Passo 4: Integração com Web App

Adicionar ao `src/web_app.py`:

```python
from tiktok_config import tiktok_config

# ... no handler ...

def do_POST(self):
    path = urllib.parse.urlparse(self.path).path
    
    # ... existing endpoints ...
    
    # TikTok Authorization
    elif path == "/api/tiktok/authorize":
        if not tiktok_config.is_configured():
            self.send_json({"error": "TikTok not configured"}, 400)
            return
        
        self.send_json({"auth_url": tiktok_config.auth_url})
    
    # TikTok Callback
    elif path == "/api/tiktok-callback":
        code = self.get_query_param("code")
        if not code:
            self.send_json({"error": "No authorization code"}, 400)
            return
        
        # Exchange code for access token
        token = exchange_code_for_token(code)
        self.send_json({"token": token})
```

---

## Passo 5: Auto-Posting Function

Criar: `src/tiktok_uploader.py`

```python
import os
import requests
from pathlib import Path
from tiktok_config import tiktok_config

class TikTokUploader:
    """Upload clips to TikTok"""
    
    API_BASE = "https://open.tiktokapis.com/v1"
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    def upload_clip(self, video_path: str, caption: str) -> dict:
        """Upload a clip to TikTok"""
        
        if not os.path.exists(video_path):
            return {"error": "Video file not found"}
        
        # Initialize upload
        init_response = requests.post(
            f"{self.API_BASE}/post/publish/action/init",
            headers=self.headers,
            json={"source_info": {"source": "FILE_UPLOAD"}}
        )
        
        if init_response.status_code != 200:
            return {"error": f"Upload init failed: {init_response.text}"}
        
        upload_id = init_response.json()["data"]["upload_id"]
        
        # Upload video file
        with open(video_path, "rb") as f:
            files = {"video": f}
            upload_response = requests.post(
                f"{self.API_BASE}/post/publish/action/upload",
                headers=self.headers,
                params={"upload_id": upload_id},
                files=files
            )
        
        if upload_response.status_code != 200:
            return {"error": f"Video upload failed: {upload_response.text}"}
        
        # Publish post
        publish_response = requests.post(
            f"{self.API_BASE}/post/publish/action/publish",
            headers=self.headers,
            json={
                "upload_id": upload_id,
                "post_info": {
                    "desc": caption,
                    "privacy_level": "PUBLIC_TO_EVERYONE"
                }
            }
        )
        
        if publish_response.status_code == 200:
            return {
                "success": True,
                "post_id": publish_response.json().get("data", {}).get("publish_id")
            }
        else:
            return {"error": f"Publish failed: {publish_response.text}"}

def upload_to_tiktok(video_path: str, caption: str, access_token: str) -> dict:
    """Helper function for uploading clips"""
    uploader = TikTokUploader(access_token)
    return uploader.upload_clip(video_path, caption)
```

---

## Passo 6: Integrar com Pipeline de Clipes

Modificar: `src/web_app.py`

```python
async def finalize_clip(clip_path: str, caption: str):
    """Finalize clip and optionally upload to TikTok"""
    
    # Save clip locally
    output_dir = Path("outputs") / "clips"
    output_dir.mkdir(exist_ok=True)
    final_path = output_dir / f"clip_{uuid4()}.mp4"
    shutil.copy(clip_path, final_path)
    
    # Auto-upload to TikTok if enabled
    if tiktok_config.is_configured() and user_tiktok_token:
        from tiktok_uploader import upload_to_tiktok
        
        result = upload_to_tiktok(
            str(final_path),
            caption,
            user_tiktok_token
        )
        
        if result.get("success"):
            log_event("tiktok_upload_success", {
                "clip_id": final_path.stem,
                "post_id": result.get("post_id")
            })
        else:
            log_event("tiktok_upload_failed", {
                "clip_id": final_path.stem,
                "error": result.get("error")
            })
    
    return final_path
```

---

## Passo 7: Adicionar UI para TikTok Authorization

Modificar: `web/app.js`

```javascript
// TikTok authorization
async function authorizeWithTikTok() {
    const response = await fetch("/api/tiktok/authorize");
    const data = await response.json();
    
    if (data.auth_url) {
        // Redirect user to TikTok login
        window.location.href = data.auth_url;
    } else {
        showError("TikTok not configured on server");
    }
}

// Add button to UI
document.addEventListener("DOMContentLoaded", () => {
    const tiktokBtn = document.createElement("button");
    tiktokBtn.textContent = "📱 Conectar com TikTok";
    tiktokBtn.className = "btn-secondary";
    tiktokBtn.onclick = authorizeWithTikTok;
    
    const uploadSection = document.getElementById("uploadSection");
    uploadSection.appendChild(tiktokBtn);
});
```

---

## Passo 8: Testar Integração

```bash
# Local testing
export TIKTOK_CLIENT_KEY="your_key"
export TIKTOK_CLIENT_SECRET="your_secret"
export TIKTOK_ENABLED="true"

python src/web_app.py
# Acesse http://localhost:8787
# Clique em "Conectar com TikTok"
```

---

## Timeline de Setup

| Etapa | Tempo | Status |
|-------|-------|--------|
| Obter credenciais TikTok | 1-3 dias | Pendente |
| Configurar Railway variables | 5 min | Pronto |
| Implementar upload function | 30 min | Pronto |
| Testar integração | 15 min | Pronto |
| Deploy em produção | 5 min | Pronto |
| **Total** | **1-3 dias** | **Aguardando creds** |

---

## Recursos

- TikTok Developer Docs: https://developers.tiktok.com/doc/
- API Reference: https://developers.tiktok.com/doc/video-api/
- OAuth Flow: https://developers.tiktok.com/doc/login-kit/
- Video Upload: https://developers.tiktok.com/doc/video-api/

---

## Próximos Passos

1. ✅ Obter Client Key + Secret do TikTok
2. ✅ Adicionar variáveis no Railway
3. ✅ Implementar upload function
4. ✅ Testar autorização OAuth
5. ✅ Auto-upload após renderização
6. ✅ Deploy em produção

Quer que eu implemente isso agora? 🚀
