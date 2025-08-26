import requests
import os
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

def get_ngrok_url():
    try:
        tunnels = requests.get("http://localhost:4040/api/tunnels").json()["tunnels"]
        for tunnel in tunnels:
            if tunnel["proto"] == "https":
                return tunnel["public_url"]
    except Exception as e:
        print("ngrokのURL取得エラー:", e)
    return None

def update_redirect_uri(service_account_file, project_id, client_id, new_redirect_uri):
    SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES)
    authed_session = AuthorizedSession(credentials)
    url = f"https://oauth2.googleapis.com/v1/projects/{project_id}/oauthClients/{client_id}"
    # 既存のリダイレクトURIを取得
    resp = authed_session.get(url)
    if resp.status_code != 200:
        print("OAuthクライアント情報取得失敗:", resp.text)
        return
    data = resp.json()
    uris = data.get("redirect_uris", [])
    if new_redirect_uri not in uris:
        uris.append(new_redirect_uri)
    patch_data = {"redirect_uris": uris}
    patch_resp = authed_session.patch(url, json=patch_data)
    print("更新結果:", patch_resp.status_code, patch_resp.text)

if __name__ == "__main__":
    SERVICE_ACCOUNT_FILE = os.getenv("GCP_SERVICE_ACCOUNT", "service-account.json")
    PROJECT_ID = os.getenv("GCP_PROJECT_ID", "your-gcp-project-id")
    CLIENT_ID = os.getenv("GCP_OAUTH_CLIENT_ID", "your-oauth-client-id")

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        print("ngrokのURLが取得できませんでした。")
        exit(1)
    redirect_uri = f"{ngrok_url}/oauth2callback"
    print("新しいリダイレクトURI:", redirect_uri)

    update_redirect_uri(SERVICE_ACCOUNT_FILE, PROJECT_ID, CLIENT_ID, redirect_uri) 