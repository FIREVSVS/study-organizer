"""
ai_classifier.py

Grok API(xAI)를 호출해서 파일 제목/설명을 보고 어느 학문/분야에 속하는지
분류 경로를 제안받는다.

준비물:
1. https://console.x.ai 에서 API 키 발급
2. .env 파일에 GROK_API_KEY=your_key_here 저장 (.env.example 참고)
3. pip install openai python-dotenv  (Grok API는 OpenAI SDK와 호환되므로
   openai 패키지를 그대로 쓰되, base_url만 xAI 서버로 바꾼다)

주의: xAI의 모델 이름은 계속 갱신되니, 아래 GROK_MODEL 값이 만료되었다면
https://docs.x.ai/docs/models 에서 최신 모델명을 확인해서 바꿔줄 것.
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# 모델명은 바뀔 수 있음. 에러 나면 https://console.groq.com/docs/models 에서 확인.
# 주의: llama-3.3-70b-versatile 등 기존 Llama 채팅 모델은 지원 종료됨.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY가 설정되지 않았습니다. .env 파일에 "
                "GROQ_API_KEY=your_key_here 를 추가하세요."
            )
        _client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    return _client


SYSTEM_PROMPT = """너는 한 학생의 개인 학습 자료 정리를 돕는 분류 보조자다.
파일 제목과 설명을 보고, 이 자료가 어느 학문 분야에 속하는지 판단해서
'대분류 > 중분류 > (필요하면 소분류)' 형태의 경로를 제안해야 한다.

규칙:
- 이미 존재하는 카테고리 목록이 주어지면, 최대한 그 안에서 적절한 위치를 찾아라.
  기존 카테고리와 의미가 겹치는데 이름만 다르게 새로 만들지 마라.
- 정말 기존 카테고리 중 맞는 게 없을 때만 새 경로를 제안해라.
- 제외 목록(exclude)이 주어지면, 그 경로들은 다시 제안하지 마라.
- 경로 깊이는 2~3단계를 권장한다 (예: 물리 > 양자역학).
- 반드시 아래 JSON 형식으로만 답하라. 다른 설명 텍스트를 붙이지 마라.

{
  "path": ["대분류", "중분류"],
  "is_new_category": true 또는 false,
  "reasoning": "이렇게 분류한 이유를 한두 문장으로"
}
"""


def suggest_category(title: str, description: str, existing_paths: list,
                      exclude_paths: list = None) -> dict:
    """
    파일 제목/설명을 보고 카테고리 경로를 제안받는다.

    Args:
        title: 파일 제목 (사용자가 붙인 이름, 보통 분야명이 포함됨)
        description: 파일에 대한 짧은 설명 (선택 입력)
        existing_paths: 현재 존재하는 카테고리 경로 문자열 리스트
                        (예: ["물리 > 양자역학", "화학 > 고급화학"])
        exclude_paths: 이전에 제안했다가 사용자가 거절한 경로 리스트

    Returns:
        {"path": [...], "is_new_category": bool, "reasoning": str}
    """
    exclude_paths = exclude_paths or []

    user_content = (
        f"파일 제목: {title}\n"
        f"파일 설명: {description or '(설명 없음)'}\n\n"
        f"현재 존재하는 카테고리 목록:\n"
        + ("\n".join(f"- {p}" for p in existing_paths) if existing_paths else "(아직 없음)")
        + "\n\n"
    )
    if exclude_paths:
        user_content += (
            "다음 경로들은 이미 제안했다가 거절당했으니 다시 제안하지 마라:\n"
            + "\n".join(f"- {p}" for p in exclude_paths) + "\n"
        )

    client = get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    result = json.loads(content)

    # 방어적 검증: 필수 키가 없으면 예외 발생
    if "path" not in result or not isinstance(result["path"], list):
        raise ValueError(f"AI 응답 형식이 예상과 다릅니다: {content}")

    return result


if __name__ == "__main__":
    # 간단한 수동 테스트 (실제 API 키가 .env에 있어야 동작함)
    result = suggest_category(
        title="양자역학 기본정리 정리노트",
        description="슈뢰딩거 방정식과 불확정성 원리 요약",
        existing_paths=["물리 > 역학", "화학 > 고급화학"],
    )
    print(result)
