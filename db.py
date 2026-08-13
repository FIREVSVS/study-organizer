"""
db.py

계층형 카테고리(예: 물리 > 양자역학)와 파일 메타데이터를 SQLite로 관리한다.
카테고리는 자기참조 트리 구조(parent_id)로 저장되어, 깊이 제한 없이
학문 > 분야 > 세부분야 처럼 얼마든지 깊게 만들 수 있다.

실제 파일 원본은 uploads/ 폴더에 저장되고, DB에는 경로와 분류 정보만 저장한다.
"""

import sqlite3
import os
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "study_organizer.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER,
            FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE,
            UNIQUE(name, parent_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INTEGER,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------
# 카테고리 (학문/분야) 관련 함수
# ---------------------------------------------------------------------

def get_children(parent_id=None) -> list:
    """parent_id 밑의 바로 아래 자식 카테고리들을 가져온다. parent_id=None이면 최상위."""
    conn = get_db()
    if parent_id is None:
        rows = conn.execute(
            "SELECT * FROM categories WHERE parent_id IS NULL ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM categories WHERE parent_id = ? ORDER BY name", (parent_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_category(category_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_category_path(category_id: int) -> list:
    """루트부터 해당 카테고리까지의 경로를 리스트로 반환 (breadcrumb용). 예: [물리, 양자역학]"""
    path = []
    conn = get_db()
    current_id = category_id
    while current_id is not None:
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (current_id,)).fetchone()
        if row is None:
            break
        path.insert(0, dict(row))
        current_id = row["parent_id"]
    conn.close()
    return path


def find_category_by_path(path_names: list):
    """['물리', '양자역학'] 같은 이름 경로로 카테고리 id를 찾는다. 없으면 None."""
    conn = get_db()
    parent_id = None
    result_id = None
    for name in path_names:
        if parent_id is None:
            row = conn.execute(
                "SELECT * FROM categories WHERE name = ? AND parent_id IS NULL", (name,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM categories WHERE name = ? AND parent_id = ?", (name, parent_id)
            ).fetchone()
        if row is None:
            conn.close()
            return None
        parent_id = row["id"]
        result_id = row["id"]
    conn.close()
    return result_id


def find_or_create_path(path_names: list) -> int:
    """
    ['물리', '양자역학'] 같은 이름 경로를 받아서, 없는 카테고리는 만들어가며
    최종(맨 끝) 카테고리의 id를 반환한다. AI 분류 제안을 확정할 때 사용.
    """
    conn = get_db()
    parent_id = None
    for name in path_names:
        name = name.strip()
        if not name:
            continue
        if parent_id is None:
            row = conn.execute(
                "SELECT * FROM categories WHERE name = ? AND parent_id IS NULL", (name,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM categories WHERE name = ? AND parent_id = ?", (name, parent_id)
            ).fetchone()

        if row is None:
            cur = conn.execute(
                "INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id)
            )
            parent_id = cur.lastrowid
        else:
            parent_id = row["id"]

    conn.commit()
    conn.close()
    return parent_id


def get_full_tree() -> list:
    """전체 카테고리 트리를 중첩 딕셔너리 리스트로 반환한다. (AI 프롬프트에 컨텍스트로 넣기 위함)"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories ORDER BY parent_id, name").fetchall()
    conn.close()

    nodes = {r["id"]: {"id": r["id"], "name": r["name"], "children": []} for r in rows}
    roots = []
    for r in rows:
        node = nodes[r["id"]]
        if r["parent_id"] is None:
            roots.append(node)
        else:
            parent = nodes.get(r["parent_id"])
            if parent:
                parent["children"].append(node)
    return roots


def tree_to_path_lines(tree=None, prefix=None) -> list:
    """트리를 'A > B > C' 형태의 경로 문자열 리스트로 평탄화한다. (AI 프롬프트용)"""
    if tree is None:
        tree = get_full_tree()
    if prefix is None:
        prefix = []

    lines = []
    for node in tree:
        current_path = prefix + [node["name"]]
        lines.append(" > ".join(current_path))
        if node["children"]:
            lines.extend(tree_to_path_lines(node["children"], current_path))
    return lines


def delete_category(category_id: int):
    """카테고리를 삭제한다. 하위 카테고리는 CASCADE로 함께 삭제되고, 파일은 미분류로 남는다."""
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------
# 파일 관련 함수
# ---------------------------------------------------------------------

def save_uploaded_file(file_storage, title: str, description: str, category_id=None) -> int:
    """
    업로드된 파일을 uploads/ 폴더에 저장하고 DB에 메타데이터를 기록한다.
    원본 파일명 충돌을 피하기 위해 저장 파일명 앞에 uuid를 붙인다.
    """
    original_filename = file_storage.filename
    ext = os.path.splitext(original_filename)[1]
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(UPLOAD_DIR, stored_filename))

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO files (title, original_filename, stored_filename, description, "
        "category_id, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
        (title, original_filename, stored_filename, description, category_id,
         datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_file(file_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_files_in_category(category_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM files WHERE category_id = ? ORDER BY uploaded_at DESC", (category_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_uncategorized_files() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM files WHERE category_id IS NULL ORDER BY uploaded_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def move_file_to_category(file_id: int, category_id: int):
    conn = get_db()
    conn.execute("UPDATE files SET category_id = ? WHERE id = ?", (category_id, file_id))
    conn.commit()
    conn.close()


def delete_file(file_id: int):
    f = get_file(file_id)
    if f:
        path = os.path.join(UPLOAD_DIR, f["stored_filename"])
        if os.path.exists(path):
            os.remove(path)
    conn = get_db()
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()


def search_files(keyword: str) -> list:
    """제목/설명/원본파일명에서 키워드로 검색."""
    conn = get_db()
    like = f"%{keyword}%"
    rows = conn.execute(
        "SELECT * FROM files WHERE title LIKE ? OR description LIKE ? OR original_filename LIKE ? "
        "ORDER BY uploaded_at DESC",
        (like, like, like)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_files_recursive(category_id: int) -> int:
    """해당 카테고리와 그 모든 하위 카테고리에 든 파일 수의 합."""
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM files WHERE category_id = ?", (category_id,)
    ).fetchone()[0]
    children = conn.execute(
        "SELECT id FROM categories WHERE parent_id = ?", (category_id,)
    ).fetchall()
    conn.close()
    for c in children:
        total += count_files_recursive(c["id"])
    return total


def get_map_data() -> list:
    """
    지도(트리맵) 뷰에 필요한 데이터.
    최상위 분야마다 {id, name, total(하위 포함 파일 수), children: [...]} 반환.
    어린도책의 도(圖) > 필지 위계처럼, 대분류 구역 안에 하위분야 타일을 배치하기 위함.
    """
    result = []
    for top in get_children(parent_id=None):
        children = []
        for sub in get_children(parent_id=top["id"]):
            children.append({
                "id": sub["id"],
                "name": sub["name"],
                "total": count_files_recursive(sub["id"]),
            })
        direct = len(get_files_in_category(top["id"]))
        result.append({
            "id": top["id"],
            "name": top["name"],
            "total": count_files_recursive(top["id"]),
            "direct": direct,   # 하위분야 없이 대분류에 바로 든 파일 수
            "children": children,
        })
    return result

def rename_category(category_id: int, new_name: str) -> tuple:
    """
    카테고리 이름을 바꾼다.
    같은 부모 밑에 동일한 이름이 이미 있으면 UNIQUE 제약에 걸리므로,
    성공 여부와 에러 메시지를 함께 반환한다.

    Returns: (성공여부: bool, 에러메시지: str | None)
    """
    new_name = new_name.strip()
    if not new_name:
        return False, "이름이 비어 있습니다."

    conn = get_db()
    try:
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, f"같은 위치에 '{new_name}' 분야가 이미 있습니다."
    finally:
        conn.close()