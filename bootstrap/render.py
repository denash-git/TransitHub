from __future__ import annotations

from pathlib import Path
from string import Template

from . import paths


def render_template(template_path: Path, destination: Path, context: dict[str, str]) -> None:
    template = Template(template_path.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.safe_substitute(context), encoding="utf-8")


def render_runtime_files(context: dict[str, str]) -> list[Path]:
    rendered_files: list[Path] = []

    nginx_templates = {
        "nginx.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "nginx.conf",
        "stream.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "stream.conf",
        "site.conf.template": paths.SERVICE_NGINX_CONFIG_DIR / "site.conf",
    }
    for template_name, destination in nginx_templates.items():
        render_template(paths.TEMPLATES_PROXY_DIR / template_name, destination, context)
        rendered_files.append(destination)

    subpage_src = paths.TEMPLATES_SUBPAGE_DIR / f"{context['WEB_SUB_TEMPLATE']}.html.template"
    subpage_dest = paths.SERVICE_SUBPAGE_SITE_DIR / "index.html"
    render_template(subpage_src, subpage_dest, context)
    rendered_files.append(subpage_dest)

    clash_src = paths.TEMPLATES_CLASH_DIR / f"{context['CLASH_TEMPLATE']}.yaml.template"
    clash_dest = paths.SERVICE_SUBPAGE_SITE_DIR / "clash.yaml"
    render_template(clash_src, clash_dest, context)
    rendered_files.append(clash_dest)

    fake_site_src = paths.TEMPLATES_FAKESITE_DIR / context["FAKE_SITE_TEMPLATE"] / "index.html.template"
    fake_site_dest = paths.SERVICE_FAKESITE_SITE_DIR / "index.html"
    render_template(fake_site_src, fake_site_dest, context)
    rendered_files.append(fake_site_dest)

    return rendered_files
