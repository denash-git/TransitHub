from __future__ import annotations

from pathlib import Path
from string import Template

from .tgproxy import enabled as tgproxy_enabled
from . import paths


def render_template(template_path: Path, destination: Path, context: dict[str, str]) -> None:
    template = Template(template_path.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.safe_substitute(context), encoding="utf-8")


def render_runtime_files(context: dict[str, str]) -> list[Path]:
    rendered_files: list[Path] = []
    render_context = dict(context)
    render_context["EXTENSIONS_INCLUDE_BLOCK"] = (
        "    include /etc/nginx/extensions/*.conf;"
        if context.get("ENABLE_EXTENSIONS", "true").strip().lower() == "true"
        else ""
    )

    stream_routes = [
        "    map $ssl_preread_server_name $upstream_backend {\n",
        f"        {context['REALITY_DOMAIN']} reality_ingress_backend;\n",
    ]
    if tgproxy_enabled(context):
        stream_routes.append(f"        {context['TGPROXY_FAKETLS_DOMAIN']} tgproxy_backend;\n")
    stream_routes.extend(
        [
            "        default panel_ingress_backend;\n",
            "    }\n\n",
            "    upstream reality_ingress_backend {\n",
            f"        server 127.0.0.1:{context.get('STREAM_REALITY_PORT', '9447')};\n",
            "    }\n\n",
            "    upstream panel_ingress_backend {\n",
            f"        server 127.0.0.1:{context.get('STREAM_PANEL_PORT', '9446')};\n",
            "    }\n\n",
        ]
    )
    stream_routes.extend(
        [
            "    upstream reality_backend {\n",
            "        server xui:8443;\n",
            "    }\n\n",
            "    upstream panel_https_backend {\n",
            "        server 127.0.0.1:9443;\n",
            "    }\n\n",
        ]
    )
    if tgproxy_enabled(context):
        stream_routes.extend(
            [
                "    upstream tgproxy_backend {\n",
                f"        server tgproxy:{context.get('TGPROXY_PORT', '3128')};\n",
                "    }\n\n",
            ]
        )
    render_context["STREAM_ROUTING_BLOCK"] = "".join(stream_routes).rstrip()

    stream_internal_servers = [
        "    server {\n",
        f"        listen 127.0.0.1:{context.get('STREAM_REALITY_PORT', '9447')} proxy_protocol;\n",
        "        proxy_pass reality_backend;\n",
        "    }\n\n",
        "    server {\n",
        f"        listen 127.0.0.1:{context.get('STREAM_PANEL_PORT', '9446')} proxy_protocol;\n",
        "        proxy_pass panel_https_backend;\n",
        "    }\n",
    ]
    render_context["STREAM_INTERNAL_SERVER_BLOCK"] = "".join(stream_internal_servers).rstrip()

    render_context["TGPROXY_CLOAK_SERVER_BLOCK"] = ""
    if tgproxy_enabled(context):
        render_context["TGPROXY_CLOAK_SERVER_BLOCK"] = (
            "\nserver {\n"
            f"    listen {context.get('TGPROXY_CLOAK_PORT', '9444')} ssl;\n"
            "    http2 on;\n"
            f"    server_name {context['TGPROXY_FAKETLS_DOMAIN']};\n"
            "    port_in_redirect off;\n\n"
            f"    ssl_certificate {context['CERT_LIVE_DIR']}/fullchain.pem;\n"
            f"    ssl_certificate_key {context['CERT_LIVE_DIR']}/privkey.pem;\n\n"
            "    root /srv/fakesite;\n"
            "    index index.html;\n\n"
            "    location / {\n"
            "        try_files $uri $uri/ /index.html;\n"
            "    }\n"
            "}\n"
        )

    nginx_templates = {
        "nginx.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "nginx.conf",
        "stream.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "stream.conf",
        "site.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "site.conf",
    }
    for template_name, destination in nginx_templates.items():
        render_template(paths.TEMPLATES_PROXY_DIR / template_name, destination, render_context)
        rendered_files.append(destination)

    subpage_src = paths.TEMPLATES_SUBPAGE_DIR / f"{context['WEB_SUB_TEMPLATE']}.html.template"
    subpage_dest = paths.SERVICE_CLIENT_PAGE_DIR / "index.html"
    render_template(subpage_src, subpage_dest, context)
    rendered_files.append(subpage_dest)

    clash_src = paths.TEMPLATES_CLASH_DIR / f"{context['CLASH_TEMPLATE']}.yaml.template"
    clash_dest = paths.SERVICE_CLIENT_PAGE_DIR / "clash.yaml"
    render_template(clash_src, clash_dest, context)
    rendered_files.append(clash_dest)

    fake_site_src = paths.TEMPLATES_FAKESITE_DIR / context["FAKE_SITE_TEMPLATE"] / "index.html.template"
    fake_site_dest = paths.SERVICE_FAKE_SITE_DIR / "index.html"
    render_template(fake_site_src, fake_site_dest, context)
    rendered_files.append(fake_site_dest)

    if tgproxy_enabled(context):
        tgproxy_src = paths.TEMPLATES_TGPROXY_DIR / "config.toml.template"
        tgproxy_dest = paths.SERVICE_TGPROXY_CONFIG_PATH
        render_template(tgproxy_src, tgproxy_dest, context)
        rendered_files.append(tgproxy_dest)

    return rendered_files
