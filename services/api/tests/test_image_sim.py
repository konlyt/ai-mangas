"""
图像相似度纯函数（app/utils/image_sim.py）冒烟测试。

覆盖点：
    1. 相同图像综合相似度 score≈1.0；
    2. 不同图像（正/反向渐变，结构完全互补）score<0.9；
    3. 非法输入（空字节流 / 非图像字节 / 非法哈希串）抛 ValueError；
    4. 感知哈希与汉明距离的基本性质（同图哈希一致、距离为 0、哈希为 16 位十六进制）。
"""

import io

import pytest
from PIL import Image, ImageDraw

from app.utils.image_sim import (
    combined_similarity,
    hamming_distance,
    histogram_similarity,
    perceptual_hash,
)

# 测试图像尺寸（正方形）
_IMG_SIZE = 128


def _make_gradient_png(invert: bool = False) -> bytes:
    """生成确定性的横向灰度渐变 PNG 图像字节流。

    使用逐列画线的确定性渐变（无随机成分），invert=True 时输出
    黑白反转版本 —— 与原图结构完全互补，便于构造"结构不同"的对照样本。

    Args:
        invert: 是否黑白反转。

    Returns:
        bytes: PNG 格式图像字节流。
    """
    img = Image.new("L", (_IMG_SIZE, _IMG_SIZE))
    draw = ImageDraw.Draw(img)
    max_idx = _IMG_SIZE - 1
    for x in range(_IMG_SIZE):
        value = x * 255 // max_idx
        if invert:
            value = 255 - value
        draw.line([(x, 0), (x, _IMG_SIZE - 1)], fill=value)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_same_image_score_is_one():
    """完全相同的图像：综合相似度应为 1.0，哈希距离为 0。

    Returns:
        None
    """
    img = _make_gradient_png()
    result = combined_similarity(img, img)
    assert result["score"] == pytest.approx(1.0)
    assert result["hash_similarity"] == pytest.approx(1.0)
    assert result["histogram_similarity"] == pytest.approx(1.0)
    assert hamming_distance(result["reference_hash"], result["candidate_hash"]) == 0


def test_perceptual_hash_deterministic_and_format():
    """感知哈希确定性：同一图像多次计算结果一致，且为 16 位十六进制字符串。

    Returns:
        None
    """
    img = _make_gradient_png()
    h1 = perceptual_hash(img)
    h2 = perceptual_hash(img)
    assert h1 == h2
    assert len(h1) == 16
    int(h1, 16)  # 不抛异常即为合法十六进制


def test_different_image_score_below_threshold():
    """不同图像（互补渐变）：综合得分应显著低于 0.9。

    Returns:
        None
    """
    img1 = _make_gradient_png(invert=False)
    img2 = _make_gradient_png(invert=True)
    result = combined_similarity(img1, img2)
    assert result["score"] < 0.9
    # 结构互补 → 哈希相似度应接近 0
    assert result["hash_similarity"] < 0.5


def test_histogram_similarity_same_vs_different():
    """直方图相似度：同图为 1.0；互补渐变取值分布一致也应为 1.0（颜色风格相同）。

    Returns:
        None
    """
    img1 = _make_gradient_png(invert=False)
    img2 = _make_gradient_png(invert=True)
    assert histogram_similarity(img1, img1) == pytest.approx(1.0)
    assert histogram_similarity(img1, img2) == pytest.approx(1.0)


def test_invalid_inputs_raise_value_error():
    """非法输入：空/非字节流/坏图像数据/非法哈希串均应抛 ValueError。

    Returns:
        None
    """
    img = _make_gradient_png()

    # 空字节流
    with pytest.raises(ValueError):
        perceptual_hash(b"")
    # 非 bytes 类型
    with pytest.raises(ValueError):
        perceptual_hash("not-bytes")  # type: ignore[arg-type]
    # 无法解码的图像数据
    with pytest.raises(ValueError):
        perceptual_hash(b"not-an-image-data")
    # 直方图相似度非法入参
    with pytest.raises(ValueError):
        histogram_similarity(b"", img)
    with pytest.raises(ValueError):
        histogram_similarity(img, b"junk")
    # 综合相似度非法入参
    with pytest.raises(ValueError):
        combined_similarity(b"junk", b"junk")
    # 非法哈希字符串
    with pytest.raises(ValueError):
        hamming_distance("xyz-not-hex", "0f0f0f0f0f0f0f0f")
