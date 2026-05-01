import re

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # _DojoStatCard
    content = re.sub(
        r'self\.setStyleSheet\(f"""[^"]+"""\)',
        'self.setStyleSheet(theme_manager.get_style("dv_card", "dojo"))',
        content,
        count=1
    )

    # self.btn_train
    content = re.sub(
        r'self\.btn_train\.setStyleSheet\("""[^"]+"""\)',
        'self.btn_train.setStyleSheet(theme_manager.get_style("dv_btn_train", "dojo"))',
        content,
        count=1
    )

    # self.btn_all (there might be two of these, one in classic one in dojo. Check the first match)
    # wait, btn_all has multiple occurrences? Let's replace the one that looks like dojo button.
    content = re.sub(
        r'self\.btn_all\.setStyleSheet\("""\n\s*QPushButton \{ background: transparent; border: 2px solid #5F627D;[^"]+"""\)',
        'self.btn_all.setStyleSheet(theme_manager.get_style("dv_btn_all", "dojo"))',
        content
    )

    # dojo_container
    content = re.sub(
        r'self\.dojo_container\.setStyleSheet\("""[^"]+"""\)',
        'self.dojo_container.setStyleSheet(theme_manager.get_style("dv_dojo_container", "dojo"))',
        content,
        count=1
    )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process_file('ui/deck_view.py')
print('Done multiline patches')
