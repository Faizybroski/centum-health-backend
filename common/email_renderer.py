from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

def render_email_template(template_name: str, context: dict) -> str:
    return templates.get_template(template_name).render(context)

    