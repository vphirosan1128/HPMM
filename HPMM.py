import streamlit as st
import streamlit.components.v1 as components
from PIL import Image
import io
import base64
import re
import json

# --- フォント取得用 ---
try:
    import matplotlib.font_manager as fm
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

st.set_page_config(page_title="HirosanP's Manga Maker", layout="wide", initial_sidebar_state="expanded")

@st.cache_data
def get_japanese_fonts():

    # おすすめの Google Fonts をリストに追加
    standard_jp = [
        "MS Gothic", 
        "MS Mincho", 
        "Meiryo", 
        "Yu Gothic", 
        "IPAexGothic"        "Hiragino Kaku Gothic Pro", 
        "Shippori Antic",   # セリフの定番（アンチック体）
        "Zen Maru Gothic",  # 柔らかい表現（丸ゴシック）
        "Shippori Mincho",  # ナレーション・回想（明朝体）
        "Dela Gothic One",  # 叫び・強調（極太）
        "Klee One",         # 手書き風（綺麗め）
        "Yomogi",           # 手書き風（可愛い）
        "Noto Sans JP",     # 標準的なゴシック
    ]

    if HAS_MATPLOTLIB:
        flist = fm.findSystemFonts()
        names = set()
        for fname in flist:
            try:
                names.add(fm.FontProperties(fname=fname).get_name())
            except:
                continue
        # 既存のシステムフォントと結合
        return sorted(list(set(standard_jp) | names), key=lambda x: (x not in standard_jp, x))
    return standard_jp

system_fonts = get_japanese_fonts()

# --- セッション状態の初期化 ---
if "config" not in st.session_state:
    st.session_state.config = {}

if "reset_count" not in st.session_state:
    st.session_state.reset_count = 0

if "trigger_draw" not in st.session_state:
    st.session_state.trigger_draw = False
if "svg_order" not in st.session_state:
    st.session_state.svg_order = []
# キャッシュ用
if "cached_imgs" not in st.session_state:
    st.session_state.cached_imgs = []
if "cached_svg_raw" not in st.session_state:
    st.session_state.cached_svg_raw = []

# ↓↓↓ ここを追加 ↓↓↓
if "cached_overlay" not in st.session_state:
    st.session_state.cached_overlay = None

# --- CSSスタイル ---
st.markdown("""
    <style>

/* おすすめ Google Fonts の一括読み込み */
    @import url('https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Klee+One&family=Noto+Sans+JP&family=Shippori+Antic&family=Shippori+Mincho&family=Yomogi&family=Zen+Maru+Gothic&display=swap');

    /* アプリ全体のフォントをデフォルトで「しっぽりアンチック」に設定 */
    html, body, [class*="css"], .stMarkdown {
        font-family: 'Shippori Antic', 'Noto Sans JP', sans-serif;
    }
                        
    [data-testid="stHeader"], header, [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    [data-testid="stSidebar"] { min-width: 350px !important; }
    .block-container { padding: 0 !important; margin-top: 0 !important; }
    footer { display: none !important; }
    
    .preview-scroll-container {
        width: 100%;
        height: 100vh;
        overflow: auto;
        background-color: #0e1117;
        display: block;
        padding: 0;
        margin: 0;
    }
    
    .canvas-container { position: relative; background-color: #1a1c23; line-height: 0; display: inline-block; overflow: hidden; transform-origin: top left; }
    .svg-overlay, .text-overlay { position: absolute; pointer-events: none; }
    .svg-overlay img { width: 100%; height: 100%; object-fit: fill; }
    .text-overlay { paint-order: stroke fill; }

    .upload-caption {
        font-size: 0.8rem;
        color: #ff4b4b;
        margin-top: -15px;
        margin-bottom: 15px;
    }
    .guide-box {
        background-color: #262730;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #ff4b4b;
        margin-bottom: 15px;
        font-size: 0.9rem;
    }
    .std-label {
        font-size: 14px;
        font-weight: 400;
        margin-bottom: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 内部関数 ---
def reset_all_settings():
    """セッション状態を完全にクリアして初期状態に戻す"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    # ページをリロードして初期化を反映
    # st.rerun()

def get_svg_original_ratio(content):
    """SVGのコンテンツから元の縦横比(w, h)を推測する"""
    # width と height を探す
    w_match = re.search(r'width="([\d\.]+)', content)
    h_match = re.search(r'height="([\d\.]+)', content)
    if w_match and h_match:
        return float(w_match.group(1)), float(h_match.group(1))
    
    # 見つからない場合は viewBox を探す (viewBox="0 0 100 100")
    vb_match = re.search(r'viewBox="\d+\s+\d+\s+([\d\.]+)\s+([\d\.]+)"', content)
    if vb_match:
        return float(vb_match.group(1)), float(vb_match.group(2))
    
    return 400, 300  # 取得できない場合のデフォルト

def create_manga_page(images, layout_type, canvas_w, canvas_h, bg_hex, lw, img_settings, ratios):
    fill_color = bg_hex if bg_hex.startswith('#') else f"#{bg_hex}"
    canvas = Image.new("RGB", (canvas_w, canvas_h), fill_color)
    r = [v / 100 for v in ratios]
    boxes = []
    if layout_type == "1コマ (全画面)": boxes = [{"rect": (0, 0, 1, 1), "edges": (1,1,1,1)}]
    elif layout_type == "2コマ (縦並び)": boxes = [{"rect": (0, 0, 1, r[0]), "edges": (1,1,0.5,1)}, {"rect": (0, r[0], 1, 1-r[0]), "edges": (0.5,1,1,1)}]
    elif layout_type == "3コマ (縦並び)": boxes = [{"rect": (0, 0, 1, r[0]), "edges": (1,1,0.5,1)}, {"rect": (0, r[0], 1, r[1]), "edges": (0.5,1,0.5,1)}, {"rect": (0, r[0]+r[1], 1, 1-(r[0]+r[1])), "edges": (0.5,1,1,1)}]
    elif layout_type == "4コマ (縦並び)": boxes = [{"rect": (0, 0, 1, r[0]), "edges": (1,1,0.5,1)}, {"rect": (0, r[0], 1, r[1]), "edges": (0.5,1,0.5,1)}, {"rect": (0, r[0]+r[1], 1, r[2]), "edges": (0.5,1,0.5,1)}, {"rect": (0, r[0]+r[1]+r[2], 1, 1-(r[0]+r[1]+r[2])), "edges": (0.5,1,1,1)}]
    elif layout_type == "2コマ (横並び)": boxes = [{"rect": (0, 0, r[0], 1), "edges": (1,1,1,0.5)}, {"rect": (r[0], 0, 1-r[0], 1), "edges": (1,0.5,1,1)}]
    elif layout_type == "3コマ (上段１つ、下段２つ)": boxes = [{"rect": (0, 0, 1, r[0]), "edges": (1,1,0.5,1)}, {"rect": (0, r[0], r[1], 1-r[0]), "edges": (0.5,1,1,0.5)}, {"rect": (r[1], r[0], 1-r[1], 1-r[0]), "edges": (0.5,0.5,1,1)}]
    elif layout_type == "3コマ (上段２つ、下段１つ)": boxes = [{"rect": (0, 0, r[1], r[0]), "edges": (1,1,0.5,0.5)}, {"rect": (r[1], 0, 1-r[1], r[0]), "edges": (1,0.5,0.5,1)}, {"rect": (0, r[0], 1, 1-r[0]), "edges": (0.5,1,1,1)}]
    elif layout_type == "4コマ (田の字・横切優先)": boxes = [{"rect": (0, 0, r[1], r[0]), "edges": (1,1,0.5,0.5)}, {"rect": (r[1], 0, 1-r[1], r[0]), "edges": (1,0.5,0.5,1)}, {"rect": (0, r[0], r[2], 1-r[0]), "edges": (0.5,1,1,0.5)}, {"rect": (r[2], r[0], 1-r[2], 1-r[0]), "edges": (0.5,0.5,1,1)}]

    # --- ここから追加 ---
    elif layout_type == "4コマ (田の字・縦切優先)":
        boxes = [            {"rect": (0, 0, r[0], r[1]), "edges": (1,1,0.5,0.5)}, # 左上
            {"rect": (0, r[1], r[0], 1-r[1]), "edges": (0.5,1,1,0.5)}, # 左下
            {"rect": (r[0], 0, 1-r[0], r[2]), "edges": (1,0.5,0.5,1)}, # 右上
            {"rect": (r[0], r[2], 1-r[0], 1-r[2]), "edges": (0.5,0.5,1,1)} # 右下
        ]

    elif layout_type == "3コマ (左１つ、右２つ)":
        # r[0]が左右を分ける縦線、r[1]が右側を上下に分ける横線の位置
        boxes = [
            {"rect": (0, 0, r[0], 1), "edges": (1,1,1,0.5)},        # 左（縦長）
            {"rect": (r[0], 0, 1-r[0], r[1]), "edges": (1,0.5,0.5,1)}, # 右上
            {"rect": (r[0], r[1], 1-r[0], 1-r[1]), "edges": (0.5,0.5,1,1)} # 右下
        ]

    elif layout_type == "3コマ (左２つ、右１つ)":
        # r[0]が左右を分ける縦線、r[1]が左側を上下に分ける横線の位置
        boxes = [
            {"rect": (0, 0, r[0], r[1]), "edges": (1,1,0.5,0.5)},   # 左上
            {"rect": (0, r[1], r[0], 1-r[1]), "edges": (0.5,1,1,0.5)}, # 左下
            {"rect": (r[0], 0, 1-r[0], 1), "edges": (1,0.5,1,1)}        # 右（縦長）
        ]

    elif layout_type == "4コマ (上段３つ、下段１つ)":
        # r[1], r[2] は 0〜100 の位置座標（左からの距離）
        boxes = [
            {"rect": (0, 0, r[1], r[0]), "edges": (1,1,0.5,0.5)}, 
            {"rect": (r[1], 0, r[2], r[0]), "edges": (1,0.5,0.5,0.5)},
            {"rect": (r[1]+r[2], 0, 1-(r[1]+r[2]), r[0]), "edges": (1,0.5,0.5,1)},
            {"rect": (0, r[0], 1, 1-r[0]), "edges": (0.5,1,1,1)}
        ]
    elif layout_type == "4コマ (上段１つ、下段３つ)":
        boxes = [
            {"rect": (0, 0, 1, 1-r[0]), "edges": (1,1,0.5,1)},
            {"rect": (0, r[0], r[1], r[0]), "edges": (0.5,1,1,0.5)}, 
            {"rect": (r[1], r[0], r[2], r[0]), "edges": (0.5,0.5,1,0.5)}, # ここ: r[2]がr[1]より大きい前提
            {"rect": (r[1]+r[2], r[0], 1-r[1]-r[2], r[0]), "edges": (0.5,0.5,1,1)}
        ]

    elif layout_type == "4コマ (左３つ、右１つ)":
        boxes = [
            {"rect": (0, 0, r[0], r[1]), "edges": (1,1,0.5,0.5)},
            {"rect": (0, r[1], r[0], r[2]), "edges": (0.5,1,0.5,0.5)}, # ここ: r[2]-r[1]
            {"rect": (0, r[1]+r[2], r[0], 1-r[1]-r[2]), "edges": (0.5,1,1,0.5)},
            {"rect": (r[0], 0, 1-r[0], 1), "edges": (1,0.5,1,1)}
        ]

    elif layout_type == "4コマ (左１つ、右３つ)":
        boxes = [
            {"rect": (0, 0, r[0], 1), "edges": (1,1,1,0.5)},
            {"rect": (r[0], 0, 1-r[0], r[1]), "edges": (1,0.5,0.5,1)},
            {"rect": (r[0], r[1], 1-r[0], r[2]), "edges": (0.5,0.5,0.5,1)}, # ここ: r[2]-r[1]
            {"rect": (r[0], r[1]+r[2], 1-r[0], 1-r[1]-r[2]), "edges": (0.5,0.5,1,1)}
        ]

    elif layout_type == "4コマ (上段２つ、中段１つ、下段１つ)":
        boxes = [
            {"rect": (0,        0,          r[2],   r[0]),          "edges": (1,1,0.5,0.5)},
            {"rect": (r[2],     0,          1-r[2], r[0]),          "edges": (1,0.5,0.5,1)}, 
            {"rect": (0,        r[0],       1,      r[1]),          "edges": (0.5,1,0.5,1)},
            {"rect": (0,        r[0]+r[1],  1,      1-r[0]-r[1]),   "edges": (0.5,1,1,1)}
        ]

    elif layout_type == "4コマ (上段１つ、中段２つ、下段１つ)":
        boxes = [
            {"rect": (0,        0,          1,      r[0]),          "edges": (1,1,0.5,1)},
            {"rect": (0,        r[0],       r[2],   r[1]),          "edges": (0.5,1,0.5,0.5)},
            {"rect": (r[2],     r[0],       1-r[2], r[1]),          "edges": (0.5,0.5,0.5,1)}, 
            {"rect": (0,        r[0]+r[1],  1,      1-r[0]-r[1]),   "edges": (0.5,1,1,1)}
        ]

    elif layout_type == "4コマ (上段１つ、中段１つ、下段２つ)":
        boxes = [
            {"rect": (0,        0,          1,      r[0]),          "edges": (1,1,0.5,1)},
            {"rect": (0,        r[0],       1,      r[1]),          "edges": (0.5,1,0.5,1)},
            {"rect": (0,        r[0]+r[1],  r[2],   1-r[0]-r[1]),   "edges": (0.5,1,1,0.5)},
            {"rect": (r[2],     r[0]+r[1],  1-r[2], 1-r[0]-r[1]),   "edges": (0.5,0.5,1,1)} 
        ]

    elif layout_type == "4コマ (上段２つｘ１つ、下段１つ)":
        boxes = [
            {"rect": (0,        0,                  r[1],       r[0]*r[2]),             "edges": (1,1,0.5,0.5)},
            {"rect": (0,        r[0]*r[2],          r[1],       r[0]-(r[0]*r[2])),      "edges": (0.5,1,0.5,0.5)},
            {"rect": (r[1],     0,                  1-r[1],     r[0]),                  "edges": (1,0.5,0.5,1)},
            {"rect": (0,        r[0],               1,          1-r[0]),                "edges": (0.5,1,1,1)} 
        ]

    elif layout_type == "4コマ (上段１つｘ２つ、下段１つ)":
        boxes = [
            {"rect": (0,        0,                  r[1],       r[0]),                  "edges": (1,1,0.5,0.5)},
            {"rect": (r[1],     0,                  1-r[1],     r[0]*r[2]),             "edges": (1,0.5,0.5,1)},
            {"rect": (r[1],     r[0]*r[2],          1-r[1],     r[0]-(r[0]*r[2])),      "edges": (0.5,0.5,0.5,1)},
            {"rect": (0,        r[0],               1,          1-r[0]),                "edges": (0.5,1,1,1)} 
        ]

    elif layout_type == "4コマ (上段１つ、下段２つｘ１つ)":
        boxes = [
            {"rect": (0,        0,                  1,          r[0]),                  "edges": (1,1,0.5,1)},
            {"rect": (0,        r[0],               r[1],       (1-r[0])*r[2]),         "edges": (0.5,1,0.5,0.5)},
            {"rect": (0,        r[0]+(1-r[0])*r[2], r[1],       (1-r[0])*(1-r[2])),     "edges": (0.5,1,1,0.5)},
            {"rect": (r[1],     r[0],               1-r[1],     1-r[0]),                "edges": (0.5,0.5,1,1)} 
        ]

    elif layout_type == "4コマ (上段１つ、下段１つｘ２つ)":
        boxes = [
            {"rect": (0,        0,                  1,          r[0]),                  "edges": (1,1,0.5,1)},
            {"rect": (0,        r[0],               r[1],       1-r[0]),                "edges": (0.5,1,1,0.5)},
            {"rect": (r[1],     r[0],               1-r[1],     (1-r[0])*r[2]),         "edges": (0.5,0.5,0.5,1)},
            {"rect": (r[1],     r[0]+(1-r[0])*r[2], 1-r[1],     (1-r[0])*(1-r[2])),     "edges": (0.5,1,0.5,1)}
        ]

        # x, y, w, h 上左下右

    # --- ここまで追加 ---

    for i, b in enumerate(boxes):
        if i >= len(images): break
        rx, ry, rw, rh = b["rect"]
        t, left, bottom, right = [v * lw for v in b["edges"]]
        p_w, p_h = int(canvas_w * rw - (left + right)), int(canvas_h * rh - (t + bottom))
        panel = Image.new("RGB", (max(1, p_w), max(1, p_h)), fill_color)
        s, img = img_settings[i], images[i]
        work_img = img
        if s.get('flip_h'): work_img = work_img.transpose(Image.FLIP_LEFT_RIGHT)
        if s.get('flip_v'): work_img = work_img.transpose(Image.FLIP_TOP_BOTTOM)
        img_rot = work_img.rotate(s['rotate'], resample=Image.BICUBIC, expand=True, fillcolor=fill_color)
        
        actual_scale = s['scale'] / 100.0
        base_scale = max(panel.width/img_rot.width, panel.height/img_rot.height) * actual_scale
        new_size = (int(img_rot.width * base_scale), int(img_rot.height * base_scale))
        img_res = img_rot.resize(new_size, Image.LANCZOS)
        panel.paste(img_res, ((panel.width - new_size[0])//2 + int(s['offset_x']), (panel.height - new_size[1])//2 + int(s['offset_y'])))
        canvas.paste(panel, (int(canvas_w*rx + left), int(canvas_h*ry + t)))
    return canvas

def render_manga_preview(imgs, layout, c_w, c_h, bg, lw, img_settings, ratios, svg_settings, txt_settings, preview_zoom, overlay_img=None, overlay_settings=None):
    base_img = create_manga_page(imgs, layout, c_w, c_h, bg, lw, img_settings, ratios)

    # --- ↓↓↓ ここから追加：オーバーレイ画像の合成 ↓↓↓ ---
    if overlay_img and overlay_settings:
        ov_img = overlay_img.copy().convert("RGBA")
        
        # 枠線（四角い外枠）の追加
        bw = overlay_settings.get("border_w", 0)
        bc = overlay_settings.get("border_c", "#FFFFFF")
        if bw > 0:
            new_w = ov_img.width + bw * 2
            new_h = ov_img.height + bw * 2
            border_img = Image.new("RGBA", (new_w, new_h), bc)
            border_img.paste(ov_img, (bw, bw), ov_img)
            ov_img = border_img

        # リサイズ（倍率）
        scale = overlay_settings.get("scale", 100) / 100.0
        if scale != 1.0:
            new_size = (int(ov_img.width * scale), int(ov_img.height * scale))
            if new_size[0] > 0 and new_size[1] > 0:
                ov_img = ov_img.resize(new_size, Image.LANCZOS)
        
        # 回転
        rot = overlay_settings.get("rotate", 0)
        if rot != 0:
            ov_img = ov_img.rotate(rot, resample=Image.BICUBIC, expand=True)

        # ペースト（配置）
        x = overlay_settings.get("x", 0)
        y = overlay_settings.get("y", 0)
        base_img = base_img.convert("RGBA")
        base_img.paste(ov_img, (x, y), ov_img)
        base_img = base_img.convert("RGB")
    # --- ↑↑↑ ここまで追加 ↑↑↑ ---

    buf = io.BytesIO()
    base_img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    # --- グリッド用のCSS ---
    grid_html = ""
    if show_grid:
        grid_html = f"""
        <div style="
            position: absolute; top: 0; left: 0; width: {c_w}px; height: {c_h}px;
            pointer-events: none;
            background-image: 
                linear-gradient(to right, rgba(255, 75, 75, 0.3) 3px, transparent 3px),
                linear-gradient(to bottom, rgba(255, 75, 75, 0.3) 3px, transparent 3px);
            background-size: {grid_size}px {grid_size}px;
            z-index: 9999;
        "></div>
        """

    svg_html = ""
    svg_data = []
    for s in svg_settings:

        content = s['content']
        c1 = s['color']
        a1 = s['fill_alpha']
        c2 = s['stroke_color']
        a2 = s['stroke_alpha']

        sw_val = s.get('stroke_width', 0)

        # パターンA (属性形式: stroke-width="2")
        def stroke_width_replacer(match):
            try:
                # match.group(1) は SVG内に元々書かれている数値
                orig = float(match.group(1))
                if orig > 0:
                    # 元が 5 でも 10 でも、0より大きければ UIの sw_val に書き換える
                    return f'stroke-width="{sw_val}"'
            except:
                pass
            # 元が 0 の場所は、そのまま 0 として返す
            return match.group(0)

        # パターンB (スタイル形式: stroke-width:2;)
        def stroke_style_replacer(match):
            try:
                orig = float(match.group(1))
                if orig > 0:
                    return f'stroke-width:{sw_val};'
            except:
                pass
            return match.group(0)

        content = re.sub(r'fill:\s*#FFFFFF;?', f'fill:{c1}; fill-opacity:{a1};', content, flags=re.IGNORECASE)
        content = re.sub(r'fill:\s*#000000;?', f'fill:{c2}; fill-opacity:{a2};', content, flags=re.IGNORECASE)
        content = re.sub(r'fill="\s*#FFFFFF"', f'fill="{c1}" fill-opacity="{a1}"', content, flags=re.IGNORECASE)
        content = re.sub(r'fill="\s*#000000"', f'fill="{c2}" fill-opacity="{a2}"', content, flags=re.IGNORECASE)
        content = re.sub(r'fill="white"', f'fill="{c1}" fill-opacity="{a1}"', content, flags=re.IGNORECASE)
        content = re.sub(r'fill="black"', f'fill="{c2}" fill-opacity="{a2}"', content, flags=re.IGNORECASE)
        content = re.sub(r'stroke="white"', f'stroke="{c1}" stroke-opacity="{a2}"', content, flags=re.IGNORECASE)
        content = re.sub(r'stroke="black"', f'stroke="{c2}" stroke-opacity="{a2}"', content, flags=re.IGNORECASE)

        content = re.sub(r'stroke-width="([\d\.]+)"', stroke_width_replacer, content, flags=re.IGNORECASE)
        content = re.sub(r'stroke-width:\s*([\d\.]+);?', stroke_style_replacer, content, flags=re.IGNORECASE)

        content = re.sub(r'stdDeviation="[\d\.]+"', f'stdDeviation="{s["stroke_blur"]}"', content, flags=re.IGNORECASE)

        # clean_svg = re.sub(r'\s(width|height)="[^"]*"', '', content)
        clean_svg = re.sub(r'(<svg[^>]*?)\s(?:width|height)="[^"]*"', r'\1', content, count=2, flags=re.IGNORECASE)

        if '<svg' in clean_svg and 'preserveAspectRatio' not in clean_svg:
            clean_svg = clean_svg.replace('<svg', '<svg preserveAspectRatio="none"')
        
        b64 = base64.b64encode(clean_svg.encode()).decode()
        url = f"data:image/svg+xml;base64,{b64}"
        scale_x = -1 if s['flip_h'] else 1
        scale_y = -1 if s['flip_v'] else 1
        transform = f'rotate({s["rotate"]}deg) scale({scale_x}, {scale_y})'
        svg_html += f'<div class="svg-overlay" style="left:{s["x"]}px; top:{s["y"]}px; width:{s["w"]}px; height:{s["h"]}px; transform:{transform};"><img src="{url}"></div>'
        svg_data.append({"src": url, **s})

    txt_html = ""
    for t in txt_settings:
        stroke_style = f'-webkit-text-stroke: {t["outline_w"]}px {t["outline_c"]};' if t["outline_w"] > 0 else ""
        writing_mode_style = "writing-mode: vertical-rl;" if t["writing_mode"] == "縦書き" else ""
        bold_style = "font-weight: bold;" if t["bold"] else "font-weight: normal;"
        italic_style = "font-style: italic;" if t["italic"] else "font-style: normal;"
        spacing_style = f"line-height: {t['line_height']}; letter-spacing: {t['letter_spacing']}px;"
        actual_sx = t['sx'] / 100.0
        actual_sy = t['sy'] / 100.0
        rotate_transform = f'transform: rotate({t["rotate"]}deg) scale({actual_sx}, {actual_sy}); transform-origin: top left;'
        txt_html += f'<div class="text-overlay" style="left:{t["x"]}px; top:{t["y"]}px; color:{t["color"]}; font-size:{t["size"]}px; font-family:\'{t["font"]}\', sans-serif; white-space:pre; {stroke_style} {rotate_transform} {writing_mode_style} {bold_style} {italic_style} {spacing_style}">{t["text"]}</div>'

    zoom_val = preview_zoom / 100.0
    st.markdown(f"""
        <div class="preview-scroll-container">
            <div class="canvas-container" style="width:{c_w}px; height:{c_h}px; transform: scale({zoom_val});">
                <img src="data:image/png;base64,{img_b64}" style="width:{c_w}px; height:{c_h}px;">{grid_html}{svg_html}{txt_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

    return img_b64, svg_data

def generate_save_js(img_b64, svg_data, txt_settings, c_w, c_h):
    js = f"""
    <body style="margin:0; background:transparent; display: flex; flex-direction: column; height: 100px; gap: 10px;">        
        <button id="btn_normal" style="
            display: inline-flex; align-items: center; justify-content: center; font-weight: 400; padding: 0.25rem 0.5rem; border-radius: 0.5rem;
            margin: 0px; line-height: 1.6; color: rgb(250, 250, 250); user-select: none; background-color: rgb(38, 39, 48); border: 1px solid rgba(250, 250, 250, 0.2);
            cursor: pointer; font-family: 'Source Sans Pro', sans-serif; font-size: 0.9rem; transition: background-color 200ms, border-color 200ms; white-space: nowrap;
            width: 100%; height: 45px;
        " onmouseover="this.style.backgroundColor='rgba(250, 250, 250, 0.1)'; this.style.borderColor='rgba(250, 250, 250, 0.4)';" 
           onmouseout="this.style.backgroundColor='rgb(38, 39, 48)'; this.style.borderColor='rgba(250, 250, 250, 0.2)';"
        >
            全画像を保存
        </button>
        <button id="btn_bg_only" style="
            display: inline-flex; align-items: center; justify-content: center; font-weight: 400; padding: 0.25rem 0.5rem; border-radius: 0.5rem;
            margin: 0px; line-height: 1.6; color: rgb(250, 250, 250); user-select: none; background-color: rgb(38, 39, 48); border: 1px solid rgba(250, 250, 250, 0.2);
            cursor: pointer; font-family: 'Source Sans Pro', sans-serif; font-size: 0.9rem; transition: background-color 200ms, border-color 200ms; white-space: nowrap;
            width: 100%; height: 45px;
        " onmouseover="this.style.backgroundColor='rgba(250, 250, 250, 0.1)'; this.style.borderColor='rgba(250, 250, 250, 0.4)';" 
           onmouseout="this.style.backgroundColor='rgb(38, 39, 48)'; this.style.borderColor='rgba(250, 250, 250, 0.2)';"
        >
            背景画像のみ保存
        </button>
        <button id="btn_trans" style="
            display: inline-flex; align-items: center; justify-content: center; font-weight: 400; padding: 0.25rem 0.5rem; border-radius: 0.5rem;
            margin: 0px; line-height: 1.6; color: rgb(250, 250, 250); user-select: none; background-color: rgb(38, 39, 48); border: 1px solid rgba(250, 250, 250, 0.2);
            cursor: pointer; font-family: 'Source Sans Pro', sans-serif; font-size: 0.9rem; transition: background-color 200ms, border-color 200ms; white-space: nowrap;
            width: 100%; height: 45px;
        " onmouseover="this.style.backgroundColor='rgba(250, 250, 250, 0.1)'; this.style.borderColor='rgba(250, 250, 250, 0.4)';" 
           onmouseout="this.style.backgroundColor='rgb(38, 39, 48)'; this.style.borderColor='rgba(250, 250, 250, 0.2)';"
        >
            SVG/文字画像 のみ保存
        </button>
    <script>

        async function saveCanvas(e, mode) {{
            
            try {{
                const originalText = e.target.innerText;
                e.target.innerText = "保存中...";
                const cvs = document.createElement('canvas');
                cvs.width = {c_w};
                cvs.height = {c_h};
                const ctx = cvs.getContext('2d');
                const load = src => new Promise((resolve, reject) => {{ 
                    const i = new Image(); 
                    i.onload = () => resolve(i); 
                    i.onerror = () => reject(new Error("Load failed"));
                    i.src = src; 
                }});
                
                // モードが 'trans'（透過保存）以外なら背景を描く
                if (mode !== 'trans') {{
                    ctx.drawImage(await load("data:image/png;base64,{img_b64}"), 0, 0);
                }}

                // モードが 'bg'（背景のみ）以外ならSVGと文字を描く
                if (mode !== 'bg') {{
                    
                    const svgs = {json.dumps(svg_data)};
                    for (const s of svgs) {{
                        ctx.save();
                        ctx.translate(s.x + s.w/2, s.y + s.h/2);
                        ctx.rotate(s.rotate * Math.PI / 180);
                        ctx.scale(s.flip_h ? -1 : 1, s.flip_v ? -1 : 1);
                        ctx.drawImage(await load(s.src), -s.w/2, -s.h/2, s.w, s.h);
                        ctx.restore();
                    }}
                                        
                    const txts = {json.dumps(txt_settings)};
                    txts.forEach(t => {{
                        if (!t.text) return;
                        ctx.save();
                        ctx.translate(t.x, t.y);
                        ctx.rotate(t.rotate * Math.PI / 180);
                        ctx.scale(t.sx/100.0, t.sy/100.0);
                        const style = t.italic ? "italic " : "";
                        const weight = t.bold ? "bold " : "";
                        ctx.font = style + weight + t.size + "px '" + t.font + "', sans-serif";
                        ctx.textBaseline = "top";
                        
                        const lines = t.text.trimEnd().split('\\n');
                        
                        const spacing = Number(t.letter_spacing) || 0;
                        const lh = Number(t.line_height) || 1.2;
                        lines.forEach((line, lineIdx) => {{
                            if (t.writing_mode === "縦書き") {{
                                const totalLinesWidth = (lines.length - 1) * t.size * lh;
                                const xOffset = totalLinesWidth - (lineIdx * t.size * lh);

                                ctx.textAlign = "center"; 
                                const charCenterX = xOffset + (t.size / 2);
                                
                                [...line].forEach((char, charIdx) => {{
                                    const yOffset = charIdx * (t.size + spacing);
                                    if (t.outline_w > 0) {{
                                        ctx.strokeStyle = t.outline_c; 
                                        ctx.lineWidth = t.outline_w * 2;
                                        ctx.lineJoin = "round"; 
                                        ctx.strokeText(char, xOffset + (t.size / 2), yOffset);
                                    }}
                                    ctx.fillStyle = t.color; 
                                    ctx.fillText(char, xOffset + (t.size / 2), yOffset);
                                }});
                            }} else {{
                                const yOffset = lineIdx * t.size * lh;
                                let xAcc = 0;
                                [...line].forEach((char) => {{
                                    if (t.outline_w > 0) {{
                                        ctx.strokeStyle = t.outline_c; 
                                        ctx.lineWidth = t.outline_w * 2;
                                        ctx.lineJoin = "round"; 
                                        ctx.strokeText(char, xAcc, yOffset);
                                    }}
                                    ctx.fillStyle = t.color; 
                                    ctx.fillText(char, xAcc, yOffset);
                                    xAcc += ctx.measureText(char).width + spacing;
                                }});
                            }}
                        }});
                        ctx.restore();
                    }});
                }}                

                const a = document.createElement('a'); 
                // 透過保存の場合はファイル名を少し変えて区別しやすくしています
                if (mode === 'trans') a.download = 'manga_transparent.png';
                else if (mode === 'bg') a.download = 'manga_background.png';
                else a.download = 'manga.png';                
                
                a.href = cvs.toDataURL('image/png'); 
                a.click();
                setTimeout(() => {{ e.target.innerText = originalText; }}, 1000);
            }} catch (err) {{
                console.error("Save Error:", err);
                alert("保存中にエラーが発生しました。");
                e.target.innerText = isTrans ? "透過保存 (SVG/文字)" : "画像を保存";
            }}
        }}

        document.getElementById('btn_normal').onclick = (e) => saveCanvas(e, 'all');
        document.getElementById('btn_trans').onclick = (e) => saveCanvas(e, 'trans');
        document.getElementById('btn_bg_only').onclick = (e) => saveCanvas(e, 'bg');    
    
    </script>
    </body>
    """
    return js

def sync_all_settings_to_state(num_txt_local, current_svg_order):
    st.session_state.config["canvas"] = {"w": c_w, "h": c_h, "bg": bg, "lw": lw}
    st.session_state.config["preview_zoom"] = preview_zoom
    st.session_state.config["layout"] = {"type": layout, "ratios": ratios}
    new_imgs = []
    for i in range(len(img_settings)):
        new_imgs.append({
            'filename': img_settings[i]['filename'],
            'scale': st.session_state.get(f"s{i}", 100),
            'rotate': st.session_state.get(f"r{i}", 0),
            'offset_x': st.session_state.get(f"x{i}", 0),
            'offset_y': st.session_state.get(f"y{i}", 0),
            'flip_h': st.session_state.get(f"ifh{i}", False),
            'flip_v': st.session_state.get(f"ifv{i}", False),
        })
    st.session_state.config["images"] = new_imgs
    new_svgs = []
    for name in current_svg_order:
        new_svgs.append({
            'filename': name,
            'color': st.session_state.get(f"fc_{name}", "#FFFFFF"),
            'fill_alpha': st.session_state.get(f"fa_{name}", 1.0),
            'stroke_color': st.session_state.get(f"sc_{name}", "#000000"),
            'stroke_alpha': st.session_state.get(f"sa_{name}", 1.0),
            'w': st.session_state.get(f"sw_{name}", 400),
            'h': st.session_state.get(f"sh_{name}", 300),
            'flip_h': st.session_state.get(f"sfh_{name}", False),
            'flip_v': st.session_state.get(f"sfv_{name}", False),
            'x': st.session_state.get(f"sx_{name}", 100),
            'y': st.session_state.get(f"sy_{name}", 100),
            'rotate': st.session_state.get(f"svgr_{name}", 0),
            'stroke_width': st.session_state.get(f"swd_{name}", 2),
            'stroke_blur': st.session_state.get(f"sbd_{name}", 0.0),
        })
    st.session_state.config["svgs"] = new_svgs
    new_txts = []
    for i in range(num_txt_local):
        new_txts.append({
            'text': st.session_state.get(f"tv{i}", ""),
            'font': st.session_state.get(f"tf{i}", "MS Gothic"),
            'writing_mode': st.session_state.get(f"td{i}", "横書き"),
            'bold': st.session_state.get(f"tb{i}", False),
            'italic': st.session_state.get(f"ti{i}", False),
            'sy': st.session_state.get(f"tsy{i}", 100),
            'sx': st.session_state.get(f"tsx{i}", 100),
            'line_height': st.session_state.get(f"tlh{i}", 1.2),
            'letter_spacing': st.session_state.get(f"tls{i}", 0),
            'size': st.session_state.get(f"ts{i}", 60),
            'rotate': st.session_state.get(f"trt{i}", 0),
            'x': st.session_state.get(f"tx{i}", 150),
            'y': st.session_state.get(f"ty{i}", 150),
            'color': st.session_state.get(f"tc{i}", "#000000"),
            'outline_c': st.session_state.get(f"oc{i}", "#FFFFFF"),
            'outline_w': st.session_state.get(f"ow{i}", 4)
        })
    st.session_state.config["texts"] = new_txts
    st.session_state.config["num_txt"] = num_txt_local

    # ↓↓↓ ここから追加 ↓↓↓
    if st.session_state.cached_overlay:
        st.session_state.config["overlay"] = {
            'scale': st.session_state.get("ov_scale", 100),
            'rotate': st.session_state.get("ov_rotate", 0),
            'x': st.session_state.get("ov_x", 0),
            'y': st.session_state.get("ov_y", 0),
            'border_w': st.session_state.get("ov_bw", 0),
            'border_c': st.session_state.get("ov_bc", "#FFFFFF"),
            'filename': getattr(st.session_state.cached_overlay, 'filename', 'overlay.png')
        }
    else:
        st.session_state.config["overlay"] = {}

# --- メインロジック ---

img_settings = []
svg_settings = []
txt_settings = []
overlay_settings = {}
ratios = []
valid_state = True

with st.sidebar:
    # --- サイドバー設定項目 ---
    # conf_file = st.file_uploader("設定を読み込む", type=["json"])

    conf_file = st.file_uploader(
        "設定を読み込む", 
        type=["json"], 
        key=f"json_uploader_{st.session_state.reset_count}"
    )


    if conf_file:
        temp_config = json.load(conf_file)
        guide_text = "以下のファイルを手動で読み込んだ上で、設定を適用してください：<br>"
        for i, img_conf in enumerate(temp_config.get("images", [])):
            guide_text += f"・画像{i+1}: {img_conf.get('filename', '---')}<br>"

        if "overlay" in temp_config and temp_config["overlay"]:
            ov_name = temp_config["overlay"].get("filename", "---")
            guide_text += f"・オーバーレイ: {ov_name}<br>"

        for i, svg_conf in enumerate(temp_config.get("svgs", [])):
            guide_text += f"・SVG{i+1}: {svg_conf.get('filename', '---')}<br>"

        st.markdown(f'<div class="guide-box" style="color: #FF8888; border: 1px solid red;">{guide_text}</div>', unsafe_allow_html=True)

        if st.button("設定を適用"):
            # 1. JSONの設定を、今あるエキスパンダーに上から順番に割り当てる
            json_svgs = temp_config.get("svgs", [])
            current_order = st.session_state.svg_order
            
            for i in range(min(len(json_svgs), len(current_order))):
                t_name = current_order[i]
                json_svgs[i]['filename'] = t_name # JSON側の名前を実体に強制同期
                
                # 2. ウィジェットのキーに直接値を叩き込んで、表示を即時更新させる
                s_c = json_svgs[i]
                if 'color' in s_c: st.session_state[f"fc_{t_name}"] = s_c['color']
                if 'fill_alpha' in s_c: st.session_state[f"fa_{t_name}"] = float(s_c['fill_alpha'])
                if 'stroke_color' in s_c: st.session_state[f"sc_{t_name}"] = s_c['stroke_color']
                if 'stroke_alpha' in s_c: st.session_state[f"sa_{t_name}"] = float(s_c['stroke_alpha'])
                if 'w' in s_c: st.session_state[f"sw_{t_name}"] = int(s_c['w'])
                if 'h' in s_c: st.session_state[f"sh_{t_name}"] = int(s_c['h'])
                if 'flip_h' in s_c: st.session_state[f"sfh_{t_name}"] = s_c['flip_h']
                if 'flip_v' in s_c: st.session_state[f"sfv_{t_name}"] = s_c['flip_v']
                if 'x' in s_c: st.session_state[f"sx_{t_name}"] = int(s_c['x'])
                if 'y' in s_c: st.session_state[f"sy_{t_name}"] = int(s_c['y'])
                if 'rotate' in s_c: st.session_state[f"svgr_{t_name}"] = int(s_c['rotate'])
                if 'stroke_width' in s_c: st.session_state[f"swd_{t_name}"] = int(s_c['stroke_width'])
                if 'stroke_blur' in s_c: st.session_state[f"sbd_{t_name}"] = float(s_c['stroke_blur'])




            # ↓↓↓ ここから追加 ↓↓↓
            if "overlay" in temp_config and temp_config["overlay"]:
                ov = temp_config["overlay"]
                st.session_state["ov_scale"] = ov.get("scale", 100)
                st.session_state["ov_rotate"] = ov.get("rotate", 0)
                st.session_state["ov_x"] = ov.get("x", 0)
                st.session_state["ov_y"] = ov.get("y", 0)
                st.session_state["ov_bw"] = ov.get("border_w", 0)
                st.session_state["ov_bc"] = ov.get("border_c", "#FFFFFF")
            # ↑↑↑ ここまで追加 ↑↑↑

            # configを更新
            temp_config["svgs"] = json_svgs
            st.session_state.config = temp_config
            
            # 再描画ボタンと同じフラグを立てる
            st.session_state.trigger_draw = True
            
            # ★最大の原因だった st.rerun() を削除！
            # これにより処理が途切れず下に流れ、再描画ボタンを押した時と全く同じ動作になります

    conf = st.session_state.config
    c_w = st.number_input("幅", value=int(conf.get("canvas", {}).get("w", 1080)), step=10)
    c_h = st.number_input("高さ", value=int(conf.get("canvas", {}).get("h", 1920)), step=10)
    bg = st.text_input("背景色", conf.get("canvas", {}).get("bg", "#FFFFFF"))
    lw = st.number_input("枠線", value=int(conf.get("canvas", {}).get("lw", 10)), step=10)
    preview_zoom = st.slider("プレビュー表示倍率 (%)", 5, 100, int(conf.get("preview_zoom", 30)), step=5)

    show_grid = st.checkbox("グリッドを表示", value=False)
    grid_size = st.number_input("グリッド間隔 (px)", 10, 500, 100, step=10) if show_grid else 100

    layout_list = [
        "1コマ (全画面)", 
        "2コマ (縦並び)", 
        "3コマ (縦並び)", 
        "4コマ (縦並び)", 
        "2コマ (横並び)", 
        "3コマ (上段１つ、下段２つ)", 
        "3コマ (上段２つ、下段１つ)", 
        "3コマ (左１つ、右２つ)",
        "3コマ (左２つ、右１つ)",
        "4コマ (田の字・横切優先)",
        "4コマ (田の字・縦切優先)",
        "4コマ (上段３つ、下段１つ)", 
        "4コマ (上段１つ、下段３つ)",
        "4コマ (左３つ、右１つ)", 
        "4コマ (左１つ、右３つ)",
        "4コマ (上段２つ、中段１つ、下段１つ)", 
        "4コマ (上段１つ、中段２つ、下段１つ)", 
        "4コマ (上段１つ、中段１つ、下段２つ)", 
        "4コマ (上段２つｘ１つ、下段１つ)", 
        "4コマ (上段１つｘ２つ、下段１つ)", 
        "4コマ (上段１つ、下段２つｘ１つ)", 
        "4コマ (上段１つ、下段１つｘ２つ)", 
    ]

    saved_layout = conf.get("layout", {}).get("type", "1コマ (全画面)")
    layout = st.selectbox("レイアウト", layout_list, index=layout_list.index(saved_layout) if saved_layout in layout_list else 0)

    st.markdown('<p class="std-label">比率設定 (%)</p>', unsafe_allow_html=True)
    saved_r = conf.get("layout", {}).get("ratios", [])
    if layout == "2コマ (縦並び)":
        ratios = [st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 50, step=10)]

    elif layout == "2コマ (横並び)":
        ratios = [st.number_input("幅比率", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 50, step=10)]

    elif layout in ["3コマ (縦並び)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 33, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 33, step=10)
        ratios = [r1, r2]
        if r1 + r2 > 100: valid_state = False

    elif layout in ["3コマ (上段１つ、下段２つ)", "3コマ (上段２つ、下段１つ)", "3コマ (左１つ、右２つ)", "3コマ (左２つ、右１つ)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 50, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 50, step=10)
        ratios = [r1, r2]

    elif layout in ["4コマ (縦並び)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 25, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 25, step=10)
        r3 = st.number_input("比率3", 0, 100, int(saved_r[2]) if len(saved_r) > 2 else 25, step=10)
        ratios = [r1, r2, r3]
        if r1 + r2 + r3 > 100: valid_state = False

    elif layout in ["4コマ (田の字・横切優先)", "4コマ (田の字・縦切優先)", "4コマ (上段２つｘ１つ、下段１つ)",  "4コマ (上段１つｘ２つ、下段１つ)", "4コマ (上段１つ、下段２つｘ１つ)",  "4コマ (上段１つ、下段１つｘ２つ)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 50, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 50, step=10)
        r3 = st.number_input("比率3", 0, 100, int(saved_r[2]) if len(saved_r) > 2 else 50, step=10)
        ratios = [r1, r2, r3]

    elif layout in ["4コマ (上段３つ、下段１つ)", "4コマ (上段１つ、下段３つ)", "4コマ (左３つ、右１つ)", "4コマ (左１つ、右３つ)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 50, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 33, step=10)
        r3 = st.number_input("比率3", 0, 100, int(saved_r[2]) if len(saved_r) > 2 else 33, step=10)
        ratios = [r1, r2, r3]
        if r2 + r3 > 100: valid_state = False

    elif layout in ["4コマ (上段２つ、中段１つ、下段１つ)", "4コマ (上段１つ、中段２つ、下段１つ)", "4コマ (上段１つ、中段１つ、下段２つ)"]:
        r1 = st.number_input("比率1", 0, 100, int(saved_r[0]) if len(saved_r) > 0 else 33, step=10)
        r2 = st.number_input("比率2", 0, 100, int(saved_r[1]) if len(saved_r) > 1 else 33, step=10)
        r3 = st.number_input("比率3", 0, 100, int(saved_r[2]) if len(saved_r) > 2 else 50, step=10)
        ratios = [r1, r2, r3]
        if r1 + r2 > 100: valid_state = False

    if not valid_state:
        st.error("比率合計が100%超過")

    # 画像アップロード
    #up_imgs = st.file_uploader("画像 (最大4枚)", type=["jpg", "png"], accept_multiple_files=True)
    up_imgs = st.file_uploader("画像 (最大4枚)", type=["jpg", "png"], accept_multiple_files=True, key=f"up_imgs_{st.session_state.reset_count}")


    st.markdown('<p class="upload-caption">※ 5枚目以降の画像は無視されます</p>', unsafe_allow_html=True)
    
    # 画像キャッシュ更新
    if up_imgs is not None:
        # 1. 常にアップローダーの現在の状態（削除反映後）でリストを再構築する
        new_cached_imgs = []
        for f in up_imgs[:4]:
            img = Image.open(f).convert("RGB")
            img.filename = f.name  # ファイル名をその場で付与
            new_cached_imgs.append(img)
        
        # 2. セッション状態を最新の状態（空なら空、あればある分だけ）で上書き
        st.session_state.cached_imgs = new_cached_imgs

    saved_imgs = conf.get("images", [])
    imgs = st.session_state.cached_imgs # キャッシュから取得

    if imgs:
        for i, img_obj in enumerate(imgs):
            fname = getattr(img_obj, 'filename', f"Image_{i}")
            s_data = next((s for s in saved_imgs if s.get('filename') == fname), {})
            with st.expander(f"画像{i+1}調整: {fname}"):
                col1, col2 = st.columns(2)
                sc = col1.number_input("倍率 (%)", 10, 1000, int(s_data.get('scale', 100)), step=10, key=f"s{i}")
                rot = col2.number_input("回転", -360, 360, int(s_data.get('rotate', 0)), step=10, key=f"r{i}")
                col_fh, col_fv = st.columns(2)
                fh = col_fh.checkbox("横反転", s_data.get('flip_h', False), key=f"ifh{i}")
                fv = col_fv.checkbox("縦反転", s_data.get('flip_v', False), key=f"ifv{i}")
                ox = st.number_input("左右", value=int(s_data.get('offset_x', 0)), step=10, key=f"x{i}")
                oy = st.number_input("上下", value=int(s_data.get('offset_y', 0)), step=10, key=f"y{i}")
                img_settings.append({'filename': fname, 'scale': sc, 'rotate': rot, 'offset_x': ox, 'offset_y': oy, 'flip_h': fh, 'flip_v': fv})


    # === ↓↓↓ ここから追加：オーバーレイPNGのUI ↓↓↓ ===
    # st.markdown('<p class="std-label">フリー配置PNG (SVG・文字の下)</p>', unsafe_allow_html=True)

    # up_overlay = st.file_uploader("オーバーレイ画像 (1枚のみ)", type=["png"])
    up_overlay = st.file_uploader("オーバーレイ画像 (1枚のみ)", type=["png"], key=f"up_overlay_{st.session_state.reset_count}")    

    if up_overlay is not None:
        img = Image.open(up_overlay).convert("RGBA")
        img.filename = up_overlay.name
        st.session_state.cached_overlay = img
    else:
        st.session_state.cached_overlay = None

    if st.session_state.cached_overlay:
        s_data = conf.get("overlay", {})
        fname = getattr(st.session_state.cached_overlay, 'filename', '画像')
        with st.expander(f"オーバーレイ設定: {fname}"):
            col_o1, col_o2 = st.columns(2)
            ov_sc = col_o1.number_input("倍率 (%)", 1, 1000, int(s_data.get('scale', 100)), step=10, key="ov_scale")
            ov_rot = col_o2.number_input("回転", -360, 360, int(s_data.get('rotate', 0)), step=10, key="ov_rotate")
            ov_x = st.number_input("X位置", -2000, 4000, int(s_data.get('x', 0)), step=10, key="ov_x")
            ov_y = st.number_input("Y位置", -2000, 4000, int(s_data.get('y', 0)), step=10, key="ov_y")
            
            col_b1, col_b2 = st.columns(2)
            ov_bw = col_b1.number_input("枠線太さ", 0, 200, int(s_data.get('border_w', 0)), step=1, key="ov_bw")
            ov_bc = col_b2.text_input("枠線色", s_data.get('border_c', "#FFFFFF"), key="ov_bc")

            overlay_settings = {
                'scale': ov_sc, 'rotate': ov_rot, 'x': ov_x, 'y': ov_y, 
                'border_w': ov_bw, 'border_c': ov_bc, 'filename': fname
            }
    # === ↑↑↑ ここまで追加 ↑↑↑ ===

    # SVGアップロード
    # up_svgs = st.file_uploader("SVG (最大40個)", type=["svg"], accept_multiple_files=True)
    up_svgs = st.file_uploader("SVG (最大40個)", type=["svg"], accept_multiple_files=True, key=f"up_svgs_{st.session_state.reset_count}")    
    
    st.markdown('<p class="upload-caption">※ 41個目以降のSVGは無視されます</p>', unsafe_allow_html=True)
    
    # SVGキャッシュ更新
    # if up_svgs:
    if up_svgs is not None: # 空リストの場合でも中に入るようにする

        if len(up_svgs) == 0:
            st.session_state.cached_svg_raw = []
            st.session_state.svg_order = []

        else:

            st.session_state.cached_svg_raw = []
            for f in up_svgs[:40]:
                f.seek(0)
                st.session_state.cached_svg_raw.append({'filename': f.name, 'content': f.read().decode('utf-8')})
            
            current_names = [f.name for f in up_svgs[:40]]
            if st.session_state.svg_order != current_names:
                new_order = [name for name in st.session_state.svg_order if name in current_names]
                for name in current_names:
                    if name not in new_order: new_order.append(name)
                st.session_state.svg_order = new_order

    raw_svg_list = st.session_state.cached_svg_raw
    num_txt_val = int(conf.get("num_txt", 0))

    if raw_svg_list:
        st.markdown('<p class="std-label">SVG重なり順 (下ほど前面)</p>', unsafe_allow_html=True)
        for idx, name in enumerate(st.session_state.svg_order):
            c_btn1, c_btn2, c_txt = st.columns([1, 1, 5])
            if c_btn1.button("↑", key=f"svg_up_{idx}") and idx > 0:

                sync_all_settings_to_state(num_txt_val, st.session_state.svg_order)
                
                st.session_state.svg_order[idx], st.session_state.svg_order[idx-1] = st.session_state.svg_order[idx-1], st.session_state.svg_order[idx]
                st.session_state.trigger_draw = True
                st.rerun()
            
            if c_btn2.button("↓", key=f"svg_down_{idx}") and idx < len(st.session_state.svg_order)-1:
                
                sync_all_settings_to_state(num_txt_val, st.session_state.svg_order)

                st.session_state.svg_order[idx], st.session_state.svg_order[idx+1] = st.session_state.svg_order[idx+1], st.session_state.svg_order[idx]
                st.session_state.trigger_draw = True
                st.rerun()
            c_txt.text(f"{idx+1}: {name}")

    # SVG個別設定
    saved_svgs = conf.get("svgs", [])
    for target_name in st.session_state.svg_order:
        target_svg = next((s for s in raw_svg_list if s['filename'] == target_name), None)
        if not target_svg: continue
        s_data = next((s for s in saved_svgs if s.get('filename') == target_name), {})
        with st.expander(f"SVG設定: {target_name}"):

            # 元の比率からデフォルトサイズを計算
            orig_w, orig_h = get_svg_original_ratio(target_svg['content'])
            if orig_w >= orig_h:
                default_w, default_h = 400, int(400 * (orig_h / orig_w))
            else:
                default_h, default_w = 400, int(400 * (orig_w / orig_h))

            # 元の比率からデフォルトサイズを計算
            orig_w, orig_h = get_svg_original_ratio(target_svg['content'])
            if orig_w >= orig_h:
                default_w, default_h = 400, int(400 * (orig_h / orig_w))
            else:
                default_h, default_w = 400, int(400 * (orig_w / orig_h))

            # --- 1. ここでセッションステートを初期化する（エラー回避のための必須処理） ---
            if f"fc_{target_name}" not in st.session_state: st.session_state[f"fc_{target_name}"] = s_data.get('color', "#FFFFFF")
            if f"fa_{target_name}" not in st.session_state: st.session_state[f"fa_{target_name}"] = float(s_data.get('fill_alpha', 1.0))
            if f"sc_{target_name}" not in st.session_state: st.session_state[f"sc_{target_name}"] = s_data.get('stroke_color', "#000000")
            if f"sa_{target_name}" not in st.session_state: st.session_state[f"sa_{target_name}"] = float(s_data.get('stroke_alpha', 1.0))
            if f"swd_{target_name}" not in st.session_state: st.session_state[f"swd_{target_name}"] = int(s_data.get('stroke_width', 2))
            if f"sbd_{target_name}" not in st.session_state: st.session_state[f"sbd_{target_name}"] = float(s_data.get('stroke_blur', 0.0))
            
            if f"sw_{target_name}" not in st.session_state: st.session_state[f"sw_{target_name}"] = int(s_data.get('w', default_w))
            if f"sh_{target_name}" not in st.session_state: st.session_state[f"sh_{target_name}"] = int(s_data.get('h', default_h))
            if f"sfh_{target_name}" not in st.session_state: st.session_state[f"sfh_{target_name}"] = s_data.get('flip_h', False)
            if f"sfv_{target_name}" not in st.session_state: st.session_state[f"sfv_{target_name}"] = s_data.get('flip_v', False)
            if f"sx_{target_name}" not in st.session_state: st.session_state[f"sx_{target_name}"] = int(s_data.get('x', 100))
            if f"sy_{target_name}" not in st.session_state: st.session_state[f"sy_{target_name}"] = int(s_data.get('y', 100))
            if f"svgr_{target_name}" not in st.session_state: st.session_state[f"svgr_{target_name}"] = int(s_data.get('rotate', 0))

            # --- 2. ウィジェットからは「初期値(value)」を削除し、引数をキーワードで明示する ---
            col_c1, col_c2 = st.columns(2)
            f_color = col_c1.text_input("塗り色", key=f"fc_{target_name}")
            f_alpha = col_c2.number_input("塗り透過 (0-1.0)", min_value=0.0, max_value=1.0, step=0.1, key=f"fa_{target_name}")
            s_color = col_c1.text_input("枠線色", key=f"sc_{target_name}")
            s_alpha = col_c2.number_input("枠線透過 (0-1.0)", min_value=0.0, max_value=1.0, step=0.1, key=f"sa_{target_name}")
            s_width = col_c1.number_input("枠線幅", min_value=0, max_value=500, step=1, key=f"swd_{target_name}")
            s_blur = col_c2.number_input("枠線ぼかし", min_value=0.0, max_value=50.0, step=0.1, key=f"sbd_{target_name}")

            col1, col2 = st.columns(2)
            svg_w = col1.number_input("幅", min_value=10, max_value=4000, step=10, key=f"sw_{target_name}")
            svg_h = col2.number_input("高", min_value=10, max_value=4000, step=10, key=f"sh_{target_name}")
            sfh = st.checkbox("横反転", key=f"sfh_{target_name}")
            sfv = st.checkbox("縦反転", key=f"sfv_{target_name}")
            svg_x = st.number_input("X位置", min_value=-1000, max_value=4000, step=10, key=f"sx_{target_name}")
            svg_y = st.number_input("Y位置", min_value=-1000, max_value=4000, step=10, key=f"sy_{target_name}")
            svg_rot = st.number_input("回転", min_value=-360, max_value=360, step=10, key=f"svgr_{target_name}")

            svg_settings.append({
                'filename': target_name, 
                'content': target_svg['content'], 
                'w': svg_w, 
                'h': svg_h, 
                'x': svg_x, 
                'y': svg_y, 
                'rotate': svg_rot, 
                'flip_h': sfh, 
                'flip_v': sfv, 
                'color': f_color, 
                'fill_alpha': f_alpha, 
                'stroke_color': s_color, 
                'stroke_alpha': s_alpha, 
                'stroke_width': s_width, 
                'stroke_blur': s_blur
            })
                        
    # テキスト設定
    num_txt = st.number_input("テキスト数 (最大40個)", 0, 40, num_txt_val)
    saved_txts = conf.get("texts", [])
    for i in range(num_txt):
        s_data = saved_txts[i] if i < len(saved_txts) else {}
        with st.expander(f"テキスト{i+1}"):
            t_val = st.text_area("内容", s_data.get('text', "入力"), key=f"tv{i}")
            t_font = st.selectbox("フォント", system_fonts, index=system_fonts.index(s_data.get('font', "MS Gothic")) if s_data.get('font') in system_fonts else 0, key=f"tf{i}")
            t_dir = st.radio("方向", ["横書き", "縦書き"], index=0 if s_data.get('writing_mode') == "横書き" else 1, horizontal=True, key=f"td{i}")
            col_b, col_i = st.columns(2)
            tb = col_b.checkbox("太字", s_data.get('bold', False), key=f"tb{i}")
            ti = col_i.checkbox("斜体", s_data.get('italic', False), key=f"ti{i}")
            tsy = st.number_input("縦倍率 (%)", 10, 500, int(s_data.get('sy', 100)), step=10, key=f"tsy{i}")
            tsx = st.number_input("横倍率 (%)", 10, 500, int(s_data.get('sx', 100)), step=10, key=f"tsx{i}")
            tlh = st.number_input("行間", 0.1, 10.0, float(s_data.get('line_height', 1.2)), step=0.1, key=f"tlh{i}")
            tls = st.number_input("文字間", -500, 500, int(s_data.get('letter_spacing', 0)), step=1, key=f"tls{i}")
            ts = st.number_input("サイズ", 1, 2000, int(s_data.get('size', 60)), step=1, key=f"ts{i}")
            trt = st.number_input("回転", -360, 360, int(s_data.get('rotate', 0)), step=10, key=f"trt{i}")
            tx = st.number_input("X位置", -2000, 5000, int(s_data.get('x', 150)), step=10, key=f"tx{i}")
            ty = st.number_input("Y位置", -2000, 5000, int(s_data.get('y', 150)), step=10, key=f"ty{i}")
            tc = st.text_input("文字色", s_data.get('color', "#000000"), key=f"tc{i}")
            oc = st.text_input("縁の色", s_data.get('outline_c', "#FFFFFF"), key=f"oc{i}")
            ow = st.number_input("縁太さ", 0, 200, int(s_data.get('outline_w', 4)), step=1, key=f"ow{i}")
            txt_settings.append({'text': t_val, 'font': t_font, 'size': ts, 'color': tc, 'x': tx, 'y': ty, 'outline_w': ow, 'outline_c': oc, 'rotate': trt, 'writing_mode': t_dir, 'sx': tsx, 'sy': tsy, 'bold': tb, 'italic': ti, 'line_height': tlh, 'letter_spacing': tls})

    # --- 操作・書き出しパネル (サイドバー下部に移動) ---
    st.divider()
    #st.markdown('<p class="std-label">操作・書き出し</p>', unsafe_allow_html=True)
    
    if st.button("画像を再描画", use_container_width=True):
        st.session_state.trigger_draw = True
    
    # 「画像を保存」ボタンが出現する領域
    save_button_placeholder = st.empty()

    export_data = {
        "canvas": {"w": c_w, "h": c_h, "bg": bg, "lw": lw},
        "preview_zoom": preview_zoom,
        "layout": {"type": layout, "ratios": ratios},
        "images": img_settings,
        "svgs": [{k: v for k, v in s.items() if k != 'content'} for s in svg_settings],
        "texts": txt_settings,
        "num_txt": num_txt,
        "overlay": overlay_settings  # ← これを追加
    }
    st.download_button(label="設定ファイルを保存", data=json.dumps(export_data, indent=4, ensure_ascii=False), file_name="manga_config.json", mime="application/json", use_container_width=True)

    if st.button("すべての設定をリセット", use_container_width=True, type="secondary"):
        # 現在のカウントを一時保存
        current_count = st.session_state.reset_count
        
        # 完全に全ての設定とキャッシュを消去
        st.session_state.clear()
        
        # カウントを1増やして復元（これで次回描画時にアップローダーが新品になる）
        st.session_state.reset_count = current_count + 1
        
        # 画面を再描画
        st.rerun()

with st.sidebar:
    st.divider()
    st.sidebar.caption("関連リンク")
    st.sidebar.markdown("""
    
    - [作者の販売作品(18禁)](https://www.patreon.com/posts/my-products-for-147807548)
    - [オノマトペ集(有料)](https://crimson-hard.booth.pm/items/8189955)
    - [ReadMe](https://note.com/vphirosan1128/n/n2d18a4593f78)
    - [SVGファイルの作り方](https://note.com/vphirosan1128/n/n8d81c08ed1d8)
    - [解説動画1](https://www.youtube.com/watch?v=lWi3BRBLUvs)
    - [解説動画2](https://www.youtube.com/watch?v=8_X5h49XGHw)
    - [Web版](https://vphirosan1128-hpmm.streamlit.app/)
    - [ローカル版配布サイト](https://www.patreon.com/posts/man-hua-sheng-156257970)
    """)

# --- 描画処理 & 保存ボタン生成 ---
if (st.session_state.cached_imgs and valid_state) or st.session_state.trigger_draw:
    img_b64, svg_data = render_manga_preview(st.session_state.cached_imgs, layout, c_w, c_h, bg, lw, img_settings, ratios, svg_settings, txt_settings, preview_zoom, st.session_state.cached_overlay, overlay_settings)
    with save_button_placeholder:
        save_js = generate_save_js(img_b64, svg_data, txt_settings, c_w, c_h)
        components.html(save_js, height=120)
    st.session_state.trigger_draw = False