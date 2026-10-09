"""
分镜拖拽重排（SB-04）冒烟测试。

覆盖点：
    1. 造 3 条分镜后 PUT /storyboard/reorder 按新顺序换序，
       断言返回按新 sequence 升序且 ID 顺序与请求一致；
    2. ordered_ids 缺失（少于现有分镜）→ 40001；
    3. ordered_ids 混入跨项目分镜 ID（与现有集合不匹配）→ 40001；
    4. 重复 ID → 40001。
"""

from app.core.response import ErrorCode

# 统一 API 前缀
API_PREFIX = "/api/v1"


async def test_reorder_success(auth_client, make_project_with_storyboards):
    """换序成功：3 条分镜按 [3,1,2] 重排后 sequence 重写为 1..3。

    Args:
        auth_client: 已登录测试客户端。
        make_project_with_storyboards: 项目 + 分镜一站式造数夹具。

    Returns:
        None
    """
    seed = await make_project_with_storyboards(count=3)
    project_id = seed["project_id"]
    ids = seed["storyboard_ids"]
    assert len(ids) == 3

    # 期望新顺序：原第 3 条 → 第 1，原第 1 条 → 第 2，原第 2 条 → 第 3
    new_order = [ids[2], ids[0], ids[1]]

    resp = await auth_client.put(
        f"{API_PREFIX}/projects/{project_id}/storyboard/reorder",
        json={"ordered_ids": new_order},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0

    data = body["data"]
    assert [item["id"] for item in data] == new_order, "返回应按新顺序排列"
    assert [item["sequence"] for item in data] == [1, 2, 3], "sequence 应重写为 1..n"


async def test_reorder_missing_id_returns_40001(auth_client, make_project_with_storyboards):
    """ordered_ids 缺失（少一个分镜 ID）→ 参数错误 40001。

    Args:
        auth_client: 已登录测试客户端。
        make_project_with_storyboards: 项目 + 分镜一站式造数夹具。

    Returns:
        None
    """
    seed = await make_project_with_storyboards(count=3)
    project_id = seed["project_id"]
    ids = seed["storyboard_ids"]

    resp = await auth_client.put(
        f"{API_PREFIX}/projects/{project_id}/storyboard/reorder",
        json={"ordered_ids": ids[:2]},  # 3 条分镜只传 2 条
    )
    body = resp.json()
    assert body["code"] == ErrorCode.PARAM_ERROR


async def test_reorder_cross_project_id_returns_40001(auth_client, make_project_with_storyboards):
    """ordered_ids 混入跨项目分镜 ID（总量对不上）→ 参数错误 40001。

    Args:
        auth_client: 已登录测试客户端。
        make_project_with_storyboards: 项目 + 分镜一站式造数夹具。

    Returns:
        None
    """
    seed_a = await make_project_with_storyboards(count=3)
    seed_b = await make_project_with_storyboards(count=1)

    # 项目 A 的部分分镜 + 项目 B 的分镜 → 与项目 A 现有分镜集合不一致
    mixed_ids = seed_a["storyboard_ids"][:2] + seed_b["storyboard_ids"]

    resp = await auth_client.put(
        f"{API_PREFIX}/projects/{seed_a['project_id']}/storyboard/reorder",
        json={"ordered_ids": mixed_ids},
    )
    body = resp.json()
    assert body["code"] == ErrorCode.PARAM_ERROR


async def test_reorder_duplicate_id_returns_40001(auth_client, make_project_with_storyboards):
    """ordered_ids 含重复 ID → 参数错误 40001。

    Args:
        auth_client: 已登录测试客户端。
        make_project_with_storyboards: 项目 + 分镜一站式造数夹具。

    Returns:
        None
    """
    seed = await make_project_with_storyboards(count=3)
    project_id = seed["project_id"]
    ids = seed["storyboard_ids"]

    resp = await auth_client.put(
        f"{API_PREFIX}/projects/{project_id}/storyboard/reorder",
        json={"ordered_ids": [ids[0], ids[0], ids[1]]},
    )
    body = resp.json()
    assert body["code"] == ErrorCode.PARAM_ERROR
