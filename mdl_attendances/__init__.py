from . import models


def post_init_hook(env):
    env["hr.attendance"].search([("check_out", "!=", False)]).action_regenerate_segments()
