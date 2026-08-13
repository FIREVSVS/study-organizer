"""
app.py

Flask 로컬 웹 서버 진입점.
실행: python app.py  ->  브라우저에서 http://127.0.0.1:5000 접속

라우트:
  /                       최상위 분야 목록 (물리, 화학, 역사 ... 사용자가 만들어감)
  /category/<id>          해당 분야의 하위분야 + 그 안의 파일 목록
  /upload                 파일 업로드 (분류를 직접 고를 수도, AI에게 맡길 수도 있음)
  /classify/<file_id>     AI 분류 제안 확인 화면 (예/아니요)
  /file/<id>/download     원본 파일 다운로드
  /search                 파일 검색
"""

import os
from flask import (
    Flask, render_template, request, redirect, url_for, send_from_directory, flash
)

from db import (
    init_db, get_children, get_category, get_category_path, get_full_tree,
    tree_to_path_lines, find_or_create_path, save_uploaded_file, get_file,
    get_files_in_category, get_uncategorized_files, move_file_to_category,
    delete_file, delete_category, search_files, UPLOAD_DIR, get_map_data, 
    rename_category,
)
import ai_classifier

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-if-deploying"  # 로컬 개인용이라 단순하게 둠

# 한 번의 분류 세션 동안 거절된 경로를 기억해두는 임시 저장소 (파일 id별)
# 서버 재시작하면 초기화됨 - 영구 저장할 필요는 없는 정보라 DB에 안 넣음
_rejected_paths_by_file = {}


@app.route("/")
def index():
    top_categories = get_children(parent_id=None)
    uncategorized = get_uncategorized_files()
    return render_template("index.html", categories=top_categories, uncategorized=uncategorized)


@app.route("/category/<int:category_id>")
def category_view(category_id):
    category = get_category(category_id)
    if category is None:
        return "카테고리를 찾을 수 없습니다.", 404
    breadcrumb = get_category_path(category_id)
    subcategories = get_children(parent_id=category_id)
    files = get_files_in_category(category_id)
    return render_template(
        "category.html", category=category, breadcrumb=breadcrumb,
        subcategories=subcategories, files=files
    )

@app.route("/category/<int:category_id>/rename", methods=["POST"])
def category_rename(category_id):
    new_name = request.form.get("new_name", "").strip()
    ok, error = rename_category(category_id, new_name)
    if not ok:
        flash(error)
    return redirect(url_for("category_view", category_id=category_id))

@app.route("/category/<int:category_id>/delete", methods=["POST"])
def category_delete(category_id):
    delete_category(category_id)
    return redirect(url_for("index"))


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not f or f.filename == "":
            flash("파일을 선택해주세요.")
            return redirect(url_for("upload"))
        if not title:
            title = f.filename  # 제목 안 넣으면 원본 파일명을 그대로 씀

        file_id = save_uploaded_file(f, title=title, description=description, category_id=None)
        return redirect(url_for("classify", file_id=file_id))

    # 카테고리 없이 그냥 업로드만 하고 싶을 때를 대비해 기존 트리도 넘겨줌
    tree_paths = tree_to_path_lines()
    return render_template("upload.html", tree_paths=tree_paths)


@app.route("/classify/<int:file_id>", methods=["GET", "POST"])
def classify(file_id):
    f = get_file(file_id)
    if f is None:
        return "파일을 찾을 수 없습니다.", 404

    if request.method == "POST":
        action = request.form.get("action")

        if action == "accept":
            path_str = request.form.get("suggested_path")
            path_list = [p.strip() for p in path_str.split(">")]
            category_id = find_or_create_path(path_list)
            move_file_to_category(file_id, category_id)
            _rejected_paths_by_file.pop(file_id, None)
            return redirect(url_for("category_view", category_id=category_id))

        elif action == "reject":
            rejected_path = request.form.get("suggested_path")
            _rejected_paths_by_file.setdefault(file_id, []).append(rejected_path)
            return redirect(url_for("classify", file_id=file_id))

        elif action == "manual":
            path_str = request.form.get("manual_path", "").strip()
            if path_str:
                path_list = [p.strip() for p in path_str.split(">") if p.strip()]
                category_id = find_or_create_path(path_list)
                move_file_to_category(file_id, category_id)
                _rejected_paths_by_file.pop(file_id, None)
                return redirect(url_for("category_view", category_id=category_id))

    # GET 요청이거나 reject 이후 재진입: AI에게 분류를 물어본다
    existing_paths = tree_to_path_lines()
    exclude_paths = _rejected_paths_by_file.get(file_id, [])

    ai_error = None
    suggestion = None
    try:
        suggestion = ai_classifier.suggest_category(
            title=f["title"], description=f["description"],
            existing_paths=existing_paths, exclude_paths=exclude_paths,
        )
    except Exception as e:
        ai_error = str(e)

    return render_template(
        "classify.html", f=f, suggestion=suggestion, ai_error=ai_error,
        exclude_paths=exclude_paths, existing_paths=existing_paths
    )

# 브라우저에서 바로 볼 수 있는 확장자들
PREVIEW_TYPES = {
    "image": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"],
    "pdf": [".pdf"],
    "text": [".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css",
              ".c", ".cpp", ".java", ".xml", ".log", ".ipynb"],
}


def get_preview_kind(filename: str) -> str:
    """확장자를 보고 미리보기 방식을 결정한다. 지원 안 하면 'none'."""
    ext = os.path.splitext(filename)[1].lower()
    for kind, exts in PREVIEW_TYPES.items():
        if ext in exts:
            return kind
    return "none"


@app.route("/file/<int:file_id>")
def file_view(file_id):
    """
    파일 미리보기 페이지.
    이미지/PDF는 브라우저에 바로 띄우고, 텍스트 계열은 내용을 읽어서 출력한다.
    한글(.hwp)/워드(.docx) 등은 브라우저가 열 수 없으므로 다운로드로 안내한다.
    """
    f = get_file(file_id)
    if f is None:
        return "파일을 찾을 수 없습니다.", 404

    kind = get_preview_kind(f["original_filename"])
    text_content = None
    text_error = None

    if kind == "text":
        path = os.path.join(UPLOAD_DIR, f["stored_filename"])
        try:
            # 너무 큰 파일은 앞부분만 읽어서 브라우저가 멈추는 걸 방지
            max_chars = 200_000
            with open(path, "r", encoding="utf-8", errors="replace") as fp:
                text_content = fp.read(max_chars)
                if fp.read(1):
                    text_content += "\n\n... (파일이 너무 길어 일부만 표시했습니다. 전체는 다운로드로 확인하세요.)"
        except Exception as e:
            text_error = str(e)

    breadcrumb = get_category_path(f["category_id"]) if f["category_id"] else []

    return render_template(
        "file_view.html", f=f, kind=kind,
        text_content=text_content, text_error=text_error, breadcrumb=breadcrumb
    )


@app.route("/file/<int:file_id>/raw")
def file_raw(file_id):
    """
    파일 원본을 브라우저에 인라인으로 제공한다 (다운로드가 아니라 표시용).
    <img src>, <iframe src>에서 이 주소를 사용한다.
    """
    f = get_file(file_id)
    if f is None:
        return "파일을 찾을 수 없습니다.", 404
    return send_from_directory(UPLOAD_DIR, f["stored_filename"], as_attachment=False)

@app.route("/file/<int:file_id>/download")
def download(file_id):
    f = get_file(file_id)
    if f is None:
        return "파일을 찾을 수 없습니다.", 404
    return send_from_directory(
        UPLOAD_DIR, f["stored_filename"], as_attachment=True,
        download_name=f["original_filename"]
    )


@app.route("/file/<int:file_id>/delete", methods=["POST"])
def file_delete(file_id):
    f = get_file(file_id)
    category_id = f["category_id"] if f else None
    delete_file(file_id)
    if category_id:
        return redirect(url_for("category_view", category_id=category_id))
    return redirect(url_for("index"))

@app.route("/map")
def map_view():
    """
    분야 전체를 어린도책식 타일맵으로 조망하는 페이지.
    타일 크기가 (하위 포함) 파일 수에 비례해서, 자료가 어느 분야에
    몰려 있고 어디가 비어 있는지 한눈에 보인다.
    """
    map_data = get_map_data()
    return render_template("map.html", map_data=map_data)

@app.route("/search")
def search():
    keyword = request.args.get("q", "").strip()
    results = search_files(keyword) if keyword else []
    return render_template("search.html", keyword=keyword, results=results)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
