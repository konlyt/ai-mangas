"""
图像相似度计算工具模块（角色一致性引擎核心度量）。

提供纯 Pillow 实现的轻量图像相似度度量，用于角色一致性引擎 v1：
    - perceptual_hash: 8x8 aHash 感知哈希（64 位，以 16 字符十六进制字符串表示）；
    - hamming_distance: 两个感知哈希之间的汉明距离（0~64）；
    - histogram_similarity: HSV 颜色直方图的 Pearson 相关系数（0~1）；
    - combined_similarity: 加权综合相似度（哈希 0.6 + 直方图 0.4）。

设计约束：
    - 仅依赖 Pillow，不引入 numpy / opencv 等重依赖；
    - 全部为纯函数，无 IO、无网络、无全局状态副作用；
    - 任何入参无法解析为有效图像时抛 ValueError，由调用方决定降级策略。
"""

import io

from PIL import Image

# aHash 缩放目标边长（8x8 = 64 位哈希）
_HASH_SIZE = 8
# 感知哈希总位数（用于汉明距离归一化）
_HASH_BITS = _HASH_SIZE * _HASH_SIZE
# HSV 直方图每个通道的量化 bin 数（8*8*8 = 512 维特征）
_HIST_BINS = 8
# 综合相似度中哈希得分的权重
_HASH_WEIGHT = 0.6
# 综合相似度中直方图得分的权重
_HIST_WEIGHT = 0.4


def perceptual_hash(image_bytes: bytes) -> str:
    """计算图像的 8x8 aHash 感知哈希。

    流程：解码图像 → 灰度化 → 缩放到 8x8 → 与全部像素均值比较二值化
    → 拼接为 64 位二进制 → 以 16 字符十六进制字符串返回。

    Args:
        image_bytes: 图像二进制内容（PNG/JPEG 等任意 Pillow 可解码格式）。

    Returns:
        str: 16 字符定长十六进制字符串，每位表示 64 位哈希中的一个比特。

    Raises:
        ValueError: 当 image_bytes 非法（空/非 bytes）或无法解码为图像时抛出。
    """
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
        raise ValueError("perceptual_hash 入参 image_bytes 必须为非空字节流")

    try:
        img = Image.open(io.BytesIO(bytes(image_bytes)))
        # 缩放 + 灰度化，消除尺寸与色彩干扰，保留结构信息
        img = img.convert("L").resize((_HASH_SIZE, _HASH_SIZE), Image.Resampling.LANCZOS)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"图像解码失败，无法计算感知哈希: {exc}") from exc

    # L 模式下 tobytes() 返回每像素 1 字节的原始灰度数据（8x8 图共 64 字节），
    # 等价替代 Pillow 13 将移除的 Image.getdata()（Deprecated）
    pixels = list(img.tobytes())
    avg = sum(pixels) / len(pixels)

    # 均值二值化：亮于均值为 1，否则为 0
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return f"{int(bits, 2):0{_HASH_BITS // 4}x}"


def hamming_distance(h1: str, h2: str) -> int:
    """计算两个感知哈希字符串之间的汉明距离。

    将两个十六进制哈希还原为 64 位二进制后逐位比较，统计不同位的数量。
    距离越小表示两张图结构越相似（0 表示完全一致）。

    Args:
        h1: 第一个哈希字符串（perceptual_hash 的返回值）。
        h2: 第二个哈希字符串（perceptual_hash 的返回值）。

    Returns:
        int: 汉明距离，取值范围 0~64。

    Raises:
        ValueError: 当任一哈希不是合法的十六进制字符串时抛出。
    """
    try:
        b1 = f"{int(h1, 16):0{_HASH_BITS}b}"
        b2 = f"{int(h2, 16):0{_HASH_BITS}b}"
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法的感知哈希字符串: {h1!r} / {h2!r}") from exc
    return sum(c1 != c2 for c1, c2 in zip(b1, b2))


def _quantized_hsv_histogram(img: Image.Image) -> list[int]:
    """将图像转换为量化后的 HSV 颜色直方图特征向量（内部辅助函数）。

    将 H/S/V 三个通道各 256 级量化为 8 个 bin，拼接为 512 维归一化前的
    像素计数向量，用于后续 Pearson 相关系数计算。

    Args:
        img: 已加载的 Pillow 图像对象（内部会转换为 HSV 模式）。

    Returns:
        list[int]: 512 维整数向量（H 8 bin + S 8 bin + V 8 bin 的像素计数）。
    """
    hsv = img.convert("HSV")
    hist = hsv.histogram()  # HSV 模式返回 3 通道 x 256 级 = 768 个计数

    per_bin = 256 // _HIST_BINS
    feature: list[int] = []
    for channel_idx in range(3):
        channel = hist[channel_idx * 256:(channel_idx + 1) * 256]
        for bin_idx in range(_HIST_BINS):
            start = bin_idx * per_bin
            feature.append(sum(channel[start:start + per_bin]))
    return feature


def histogram_similarity(img1_bytes: bytes, img2_bytes: bytes) -> float:
    """计算两张图像 HSV 颜色直方图的相似度（Pearson 相关系数）。

    分别提取两图的 512 维量化 HSV 直方图特征，计算 Pearson 相关系数；
    负相关与数值噪声统一截断到 [0, 1] 区间。纯色图（直方图方差为 0）
    退化为均值比较：同色为 1.0，异色为 0.0。

    Args:
        img1_bytes: 第一张图的二进制内容。
        img2_bytes: 第二张图的二进制内容。

    Returns:
        float: 直方图相似度，取值范围 0.0~1.0（保留 4 位小数）。

    Raises:
        ValueError: 当任一入参非法或无法解码为图像时抛出。
    """
    for name, data in (("img1_bytes", img1_bytes), ("img2_bytes", img2_bytes)):
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise ValueError(f"histogram_similarity 入参 {name} 必须为非空字节流")

    try:
        img1 = Image.open(io.BytesIO(bytes(img1_bytes)))
        img2 = Image.open(io.BytesIO(bytes(img2_bytes)))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"图像解码失败，无法计算直方图相似度: {exc}") from exc

    h1 = _quantized_hsv_histogram(img1)
    h2 = _quantized_hsv_histogram(img2)

    n = len(h1)
    mean1 = sum(h1) / n
    mean2 = sum(h2) / n

    cov = sum((a - mean1) * (b - mean2) for a, b in zip(h1, h2))
    var1 = sum((a - mean1) ** 2 for a in h1)
    var2 = sum((b - mean2) ** 2 for b in h2)
    denom = (var1 * var2) ** 0.5

    # 方差为 0（纯色图）时相关系数无定义，退化为均值比较
    if denom == 0:
        return 1.0 if mean1 == mean2 else 0.0

    corr = cov / denom
    return round(max(0.0, min(1.0, corr)), 4)


def combined_similarity(img1_bytes: bytes, img2_bytes: bytes) -> dict:
    """计算两张图像的综合相似度（结构 + 颜色加权融合）。

    综合得分 = 哈希相似度 * 0.6 + 直方图相似度 * 0.4：
        - 哈希相似度 = 1 - 汉明距离 / 64，反映结构/明暗分布的接近程度；
        - 直方图相似度 = HSV 直方图 Pearson 相关系数，反映色彩风格接近程度。

    Args:
        img1_bytes: 参照图的二进制内容。
        img2_bytes: 候选图的二进制内容。

    Returns:
        dict: 包含以下键的字典：
            - hash_similarity (float): 1 - 汉明距离/64，范围 0~1；
            - histogram_similarity (float): HSV 直方图相关系数，范围 0~1；
            - score (float): 加权综合得分，范围 0~1（保留 4 位小数）；
            - reference_hash (str): 参照图的感知哈希；
            - candidate_hash (str): 候选图的感知哈希。

    Raises:
        ValueError: 当任一入参非法或无法解码为图像时抛出。
    """
    h1 = perceptual_hash(img1_bytes)
    h2 = perceptual_hash(img2_bytes)

    distance = hamming_distance(h1, h2)
    hash_similarity = 1 - distance / _HASH_BITS
    hist_similarity = histogram_similarity(img1_bytes, img2_bytes)
    score = round(hash_similarity * _HASH_WEIGHT + hist_similarity * _HIST_WEIGHT, 4)

    return {
        "hash_similarity": round(hash_similarity, 4),
        "histogram_similarity": hist_similarity,
        "score": score,
        "reference_hash": h1,
        "candidate_hash": h2,
    }
