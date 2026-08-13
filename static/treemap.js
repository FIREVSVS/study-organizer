// treemap.js
// mapData는 map.html 인라인 <script>에서 전역으로 정의됨.
// 구조: [{id, name, total, direct, children: [{id, name, total}]}]
//
// 대분류 구역의 폭도, 그 안 하위분야 타일의 크기도 파일 수(total)에 비례.
// 어린도책이 필지 크기와 배치로 마을 전체를 조망하게 했던 효과를
// "내 학습 자료 분포"에 적용한 것.

const SECTION_COLORS = [
    "#e9c46a", "#a8dadc", "#f4a261", "#b5e48c",
    "#cdb4db", "#ffd6a5", "#90e0ef", "#f1c0e8",
];

function renderTreemap() {
    const container = document.getElementById("treemap");
    if (!container || !mapData.length) return;

    // 파일이 하나도 없는 분야도 최소 크기(1)로 취급해서 보이게 함
    const weightOf = (n) => Math.max(n, 1);

    const grandTotal = mapData.reduce((s, d) => s + weightOf(d.total), 0);

    mapData.forEach((top, i) => {
        const section = document.createElement("div");
        section.className = "map-section";
        section.style.borderColor = SECTION_COLORS[i % SECTION_COLORS.length];

        // 구역 헤더 (대분류 이름 + 총 파일 수) - 클릭하면 그 분야로 이동
        const header = document.createElement("a");
        header.className = "map-section-header";
        header.href = `/category/${top.id}`;
        header.style.background = SECTION_COLORS[i % SECTION_COLORS.length];
        header.textContent = `${top.name} (${top.total})`;
        section.appendChild(header);

        const body = document.createElement("div");
        body.className = "map-section-body";

        // 하위분야 타일들
        const items = [...top.children];
        // 대분류 바로 밑에 든 파일도 "(직접)" 타일로 표시
        if (top.direct > 0) {
            items.push({ id: top.id, name: "(직접 저장됨)", total: top.direct });
        }

        if (items.length === 0) {
            const empty = document.createElement("div");
            empty.className = "map-tile empty";
            empty.textContent = "비어 있음";
            body.appendChild(empty);
        } else {
            const sectionTotal = items.reduce((s, c) => s + weightOf(c.total), 0);
            items.forEach(child => {
                const tile = document.createElement("a");
                tile.className = "map-tile";
                tile.href = `/category/${child.id}`;
                // 타일 면적을 파일 수 비율로: flex-grow 사용
                tile.style.flexGrow = weightOf(child.total);
                // 파일 수가 많을수록 진하게
                const intensity = Math.min(weightOf(child.total) / sectionTotal, 1);
                tile.style.background = `rgba(0, 0, 0, ${0.04 + intensity * 0.10})`;
                tile.innerHTML = `<b>${child.name}</b><span>${child.total}건</span>`;
                body.appendChild(tile);
            });
        }

        section.appendChild(body);

        // 구역 전체 폭도 파일 수 비례 (최소 200px 보장)
        const widthPercent = (weightOf(top.total) / grandTotal) * 100;
        section.style.flexBasis = `max(200px, ${widthPercent}%)`;
        section.style.flexGrow = weightOf(top.total);

        container.appendChild(section);
    });
}

renderTreemap();