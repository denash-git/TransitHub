from __future__ import annotations

from pathlib import Path
from string import Template

from .mtproxy import enabled as mtproxy_enabled
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
    if mtproxy_enabled(context):
        render_context["STREAM_ROUTING_BLOCK"] = (
            "    geo $mtproxy_internal_source {\n"
            "        default 0;\n"
            f"        {context.get('MTPROXY_LOOP_MTPROXY_IP', '172.29.100.11')}/32 1;\n"
            "    }\n\n"
            '    map "$mtproxy_internal_source:$ssl_preread_server_name" $upstream_backend {\n'
            f'        0:{context["REALITY_DOMAIN"]} reality_backend;\n'
            f'        1:{context["REALITY_DOMAIN"]} reality_backend;\n'
            f'        0:{context["MTPROXY_TLS_DOMAIN"]} mtproxy_backend;\n'
            f'        1:{context["MTPROXY_TLS_DOMAIN"]} mtproxy_tls_backend;\n'
            "        default panel_https_backend;\n"
            "    }\n\n"
            "    upstream reality_backend {\n"
            "        server xui:8443;\n"
            "    }\n\n"
            "    upstream mtproxy_backend {\n"
            f"        server mtproxy:{context.get('MTPROXY_PORT', '3443')};\n"
            "    }\n\n"
            "    upstream mtproxy_tls_backend {\n"
            f"        server 127.0.0.1:{context.get('MTPROXY_TLS_BACKEND_PORT', '9444')};\n"
            "    }\n\n"
            "    upstream panel_https_backend {\n"
            "        server 127.0.0.1:9443;\n"
            "    }\n"
        )
        render_context["MTPROXY_FAKE_TLS_SERVER_BLOCK"] = (
            "\nserver {\n"
            f"    listen {context.get('MTPROXY_TLS_BACKEND_PORT', '9444')} ssl;\n"
            "    http2 on;\n"
            f"    server_name {context['MTPROXY_TLS_DOMAIN']};\n"
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
    else:
        render_context["STREAM_ROUTING_BLOCK"] = (
            "    map $ssl_preread_server_name $upstream_backend {\n"
            f"        {context['REALITY_DOMAIN']} reality_backend;\n"
            "        default panel_https_backend;\n"
            "    }\n\n"
            "    upstream reality_backend {\n"
            "        server xui:8443;\n"
            "    }\n\n"
            "    upstream panel_https_backend {\n"
            "        server 127.0.0.1:9443;\n"
            "    }\n"
        )
        render_context["MTPROXY_FAKE_TLS_SERVER_BLOCK"] = ""

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

    return rendered_files
