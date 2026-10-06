"""Make the isolated RVV trial's scope visible even when native UI is green."""


def perception_text(lead):
  if lead is None:
    return 'Cible absente : surveillez la vitesse'
  if lead.modelProb < .75:
    return 'Cible incertaine : surveillez la vitesse'
  return ''


def draw_rvv_only(rect, combined=False, perception=''):
  import pyray as rl
  from openpilot.system.ui.lib.application import FontWeight, gui_app

  height = 80 if perception else 56
  box = rl.Rectangle(rect.x + 12, rect.y + rect.height - height - 12, 385, height)
  rl.draw_rectangle_rounded(box, 0.2, 6, rl.Color(0, 0, 0, 190))
  font = gui_app.font(FontWeight.MEDIUM)
  label = 'Direction + adaptation RVV' if combined else 'RVV seul - direction manuelle'
  rl.draw_text_ex(font, label, rl.Vector2(box.x + 10, box.y + 6), 19, 0, rl.WHITE)
  rl.draw_text_ex(font, 'Sans freinage automatique', rl.Vector2(box.x + 10, box.y + 32), 17, 0, rl.ORANGE)
  if perception:
    rl.draw_text_ex(font, perception, rl.Vector2(box.x + 10, box.y + 56), 17, 0, rl.ORANGE)
