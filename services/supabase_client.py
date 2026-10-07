import httpx
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions
from config import Config

if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment variables.")


class _RetryingClient(httpx.Client):
    """
    httpx client that retries a read once if the pooled connection was dropped.

    Supabase closes idle/long-lived connections from its side; the next request
    on that connection then fails with RemoteProtocolError before reaching the
    server. Only GETs are retried so a write can never be applied twice.
    """

    def send(self, request, **kwargs):
        try:
            return super().send(request, **kwargs)
        except (httpx.RemoteProtocolError, httpx.ReadError):
            if request.method not in ("GET", "HEAD"):
                raise
            return super().send(request, **kwargs)


# supabase-py defaults to one shared HTTP/2 connection. When Supabase ends it
# (GOAWAY), every in-flight request from every Flask thread fails at once.
# HTTP/1.1 gives each request its own pooled connection instead.
_http = _RetryingClient(
    http2=False,
    timeout=httpx.Timeout(10.0),
    follow_redirects=True,
)

supabase: Client = create_client(
    Config.SUPABASE_URL,
    Config.SUPABASE_KEY,
    options=SyncClientOptions(httpx_client=_http),
)
