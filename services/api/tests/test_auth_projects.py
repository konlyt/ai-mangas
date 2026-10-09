"""
认证与项目 CRUD 冒烟测试。

覆盖点：
    1. 用户注册：成功返回统一响应结构 code==0，重复注册返回 40001；
    2. 用户登录：正确密码签发 access_token，错误密码返回 40101；
    3. 未登录访问受保护端点返回 40101；
    4. 项目全链路：创建 → 列表 → 详情 → 更新 → 删除（删除后详情 40401），
       全程断言统一响应结构 code==0 / message / data 结构。
"""

from app.core.response import ErrorCode

# 统一 API 前缀（与 conftest.API_PREFIX 保持一致，本地定义避免交叉导入）
API_PREFIX = "/api/v1"


async def test_auth_and_project_full_flow(client, auth_headers):
    """认证 + 项目 CRUD 全流程冒烟测试。

    Args:
        client: 基础测试客户端夹具（不带鉴权头）。
        auth_headers: admin 用户的 Bearer 请求头。

    Returns:
        None
    """
    # ---- 未登录访问受保护端点 → 40101 ----
    resp = await client.get(f"{API_PREFIX}/projects")
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == ErrorCode.UNAUTHORIZED
    assert body["data"] is None

    # ---- 携带 Token 继续后续流程 ----
    client.headers.update(auth_headers)

    # ---- 注册新用户 ----
    register_payload = {"username": "tester1", "password": "123456"}
    resp = await client.post(f"{API_PREFIX}/auth/register", json=register_payload)
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    assert body["message"] == "success"
    assert body["data"]["username"] == "tester1"
    assert body["data"]["quota"] == 1000

    # ---- 重复注册 → 40001 ----
    resp = await client.post(f"{API_PREFIX}/auth/register", json=register_payload)
    body = resp.json()
    assert body["code"] == ErrorCode.PARAM_ERROR

    # ---- 登录成功签发 token ----
    resp = await client.post(
        f"{API_PREFIX}/auth/login",
        json={"account": "tester1", "password": "123456"},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["access_token"]
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["user"]["username"] == "tester1"

    # ---- 错误密码登录 → 40101 ----
    resp = await client.post(
        f"{API_PREFIX}/auth/login",
        json={"account": "tester1", "password": "wrong-password"},
    )
    body = resp.json()
    assert body["code"] == ErrorCode.UNAUTHORIZED

    # ---- 创建项目 ----
    resp = await client.post(
        f"{API_PREFIX}/projects",
        json={"title": "冒烟测试项目", "genre": "热血", "style": "日漫", "raw_input": "一个少年的冒险"},
    )
    body = resp.json()
    assert body["code"] == 0
    project = body["data"]
    project_id = project["id"]
    assert project["title"] == "冒烟测试项目"
    assert project["status"] == "draft"
    assert project["aspect_ratio"] == "9:16"

    # ---- 项目列表（分页结构） ----
    resp = await client.get(f"{API_PREFIX}/projects")
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["total"] >= 1
    assert any(item["id"] == project_id for item in body["data"]["list"])

    # ---- 项目详情 ----
    resp = await client.get(f"{API_PREFIX}/projects/{project_id}")
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["id"] == project_id
    assert body["data"]["title"] == "冒烟测试项目"

    # ---- 更新项目 ----
    resp = await client.put(
        f"{API_PREFIX}/projects/{project_id}",
        json={"title": "改名后的项目"},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["title"] == "改名后的项目"

    # ---- 删除项目 ----
    resp = await client.delete(f"{API_PREFIX}/projects/{project_id}")
    body = resp.json()
    assert body["code"] == 0

    # ---- 删除后再查详情 → 40401 ----
    resp = await client.get(f"{API_PREFIX}/projects/{project_id}")
    body = resp.json()
    assert body["code"] == ErrorCode.NOT_FOUND
