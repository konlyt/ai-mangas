"""
剧本质量评分（SCR-07）与自动分集（SCR-06）冒烟测试。

覆盖点：
    1. 造项目 + 剧本（content 含 scenes）后 POST /script/score：
       测试环境 LLM 处于 mock 模式（无真实 Key），mock 返回内容不含四维评分，
       因此走兜底 estimated 路径 —— 断言四维分数均为 0-100 整数且 estimated=True；
    2. GET /script/episodes：content 无 episodes 字段时按每 3 场一集自动划分
       （7 场 → 3 集，末集 1 场），并断言 source=auto 与分集结构。
"""

from sqlalchemy import select

from app.models import Script

# 统一 API 前缀
API_PREFIX = "/api/v1"


async def test_score_script_returns_fallback_estimated(auth_client, make_project, make_script):
    """剧本评分端点：mock LLM 无四维输出时走兜底估算并标注 estimated。

    Args:
        auth_client: 已登录测试客户端。
        make_project: 项目造数夹具。
        make_script: 剧本造数夹具。

    Returns:
        None
    """
    # 造项目 + 7 场剧本
    project_id = await make_project(title="评分测试项目")
    await make_script(project_id, scene_count=7)

    resp = await auth_client.post(f"{API_PREFIX}/projects/{project_id}/script/score")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    # 四维分数与总分均为 0-100 的整数
    for dim in ("conflict", "character", "pacing", "hook_density", "overall"):
        assert dim in data, f"缺少评分维度 {dim}"
        assert isinstance(data[dim], int), f"{dim} 应为整数，实际: {type(data[dim])}"
        assert 0 <= data[dim] <= 100, f"{dim} 超出 0-100: {data[dim]}"

    # mock LLM 无法产出有效四维评分 → 必须走兜底估算路径
    assert data["estimated"] is True
    assert isinstance(data["suggestions"], list) and len(data["suggestions"]) > 0
    assert isinstance(data["summary"], str) and data["summary"]


async def test_score_script_not_found(auth_client, make_project):
    """无剧本的项目评分 → 40401。

    Args:
        auth_client: 已登录测试客户端。
        make_project: 项目造数夹具。

    Returns:
        None
    """
    project_id = await make_project(title="无剧本项目")
    resp = await auth_client.post(f"{API_PREFIX}/projects/{project_id}/script/score")
    body = resp.json()
    assert body["code"] == 40401


async def test_script_episodes_auto_division(auth_client, db_session, make_project, make_script):
    """自动分集：7 场按每 3 场一集划分为 3 集，末集 1 场。

    Args:
        auth_client: 已登录测试客户端。
        db_session: 数据库会话夹具（此处用于直查剧本 id 断言）。
        make_project: 项目造数夹具。
        make_script: 剧本造数夹具。

    Returns:
        None
    """
    project_id = await make_project(title="分集测试项目")
    script_id = await make_script(project_id, scene_count=7)

    resp = await auth_client.get(f"{API_PREFIX}/projects/{project_id}/script/episodes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    assert data["script_id"] == script_id
    assert data["source"] == "auto"

    episodes = data["episodes"]
    assert len(episodes) == 3, "7 场应按每 3 场一集划分为 3 集"
    assert [ep["episode"] for ep in episodes] == [1, 2, 3]
    assert [len(ep["scenes"]) for ep in episodes] == [3, 3, 1]
    # 每集都应带有标题与梗概字段
    for ep in episodes:
        assert ep["title"].startswith("第")
        assert isinstance(ep["synopsis"], str)


async def test_script_episodes_stored_source(auth_client, db_session, make_project, make_script):
    """content 已含 episodes 字段时直接返回（source=stored）。

    Args:
        auth_client: 已登录测试客户端。
        db_session: 数据库会话夹具（直接落库带 episodes 的剧本）。
        make_project: 项目造数夹具。
        make_script: 剧本造数夹具（占位，保证项目有初始剧本后再覆盖更新）。

    Returns:
        None
    """
    project_id = await make_project(title="存量分集项目")
    await make_script(project_id, scene_count=1)

    # 直接改写剧本 content，预置 episodes 结构
    stored_episodes = [
        {"episode": 1, "title": "开场", "synopsis": "少年出发", "scenes": []},
        {"episode": 2, "title": "决战", "synopsis": "终极对决", "scenes": []},
    ]
    result = await db_session.execute(select(Script).where(Script.project_id == project_id))
    script = result.scalar_one()
    script.content = {"title": "存量剧本", "episodes": stored_episodes}
    await db_session.commit()

    resp = await auth_client.get(f"{API_PREFIX}/projects/{project_id}/script/episodes")
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["source"] == "stored"
    assert body["data"]["episodes"] == stored_episodes
