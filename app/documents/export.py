"""Write database annotations to a PDF copy using standard PDF annotations."""
import pymupdf

from ..core.errors import ServiceError


def annotated_pdf(path, items):
    with pymupdf.open(path) as doc:
        note_slots = {}
        for item in items:
            if not 1 <= item['page'] <= len(doc):
                raise ServiceError(409, '批注页码与 PDF 不匹配，未导出')
            page = doc[item['page'] - 1]
            w, h = page.rect.width, page.rect.height
            matrix = page.derotation_matrix
            def point(x, y):
                return pymupdf.Point(x * w, y * h) * matrix
            def rectangle(r):
                x, y, rw, rh = r
                return pymupdf.Quad([point(x,y),point(x+rw,y),point(x,y+rh),point(x+rw,y+rh)])
            color = pymupdf.sRGB_to_pdf(int(item['color'].lstrip('#'),16))
            kind = item['kind']
            made = []
            if kind == 'highlight' and item['rects']:
                made.append(page.add_highlight_annot([rectangle(r) for r in item['rects']]))
            elif kind == 'ink' and len(item['points']) >= 2:
                made.append(page.add_ink_annot([[tuple(point(x,y)) for x,y in item['points']]]))
            else:
                slot = note_slots.get(item['page'], 0)
                note_slots[item['page']] = slot + 1
                p = rectangle(item['rects'][0]).rect.tl if item['rects'] else point(.94,.05+min(slot*.04,.85))
                made.append(page.add_text_annot(p, item['content'] or item['quote']))
            for ann in made:
                origin = {'user':'Personal','ai':'AI guide','ai_adopted':'Adopted AI'}.get(item['origin'],'Personal')
                ann.set_info(title=f'Firework · {origin}',content=item['content'] or item['quote'],subject=origin)
                ann.set_colors(stroke=color)
                if kind == 'highlight':
                    ann.set_opacity(.35)
                ann.update()
        return doc.tobytes(garbage=3, deflate=True)


def markdown(title, row, items):
    out = [f'# {title}', f"\n版本：{row['label']}\n\nPDF SHA-256：`{row['file_hash']}`"]
    for item in items:
        out.extend([f"\n## 第 {item['page']} 页 · {item['kind']} · {item['origin']}", item['quote'], item['content']])
    return '\n\n'.join(out)
