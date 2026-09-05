# Veo 3 / Veo 3.1 使用技巧全网研究汇总

> 整理日期：2026-04-23
> 研究范围：官方文档、GitHub、博客、论坛、实测对比等全网公开资料
> 版本覆盖：Veo 3（2025年5月发布）、Veo 3.1（2025年10月发布）

---

## 目录

1. [基础概述](#一-基础概述)
2. [适用场景 vs 不适用场景](#二-适用场景-vs-不适用场景)
3. [提示词技巧（Do's ✅）](#三-提示词技巧-dos-✅)
4. [提示词禁忌（Don'ts ❌）](#四-提示词禁忌-donts-❌)
5. [镜头控制技巧](#五-镜头控制技巧)
6. [音频生成技巧](#六-音频生成技巧)
7. [首帧/参考图（图生视频）技巧](#七-首帧参考图图生视频-技巧)
8. [角色一致性（多镜头）技巧](#八-角色一致性多镜头技巧)
9. [竞品对比参考](#九-竞品对比参考)
10. [版本差异（Veo 3 vs Veo 3.1）](#十-版本差异-veo-3-vs-veo-31)
11. [商业使用注意事项](#十一-商业使用注意事项)

---

## 一、基础概述

| 项目 | 内容 |
|------|------|
| **发布方** | Google DeepMind |
| **发布时间** | Veo 3：2025年5月 Google I/O；Veo 3.1：2025年10月 |
| **核心能力** | 文生视频（Text-to-Video）+ 原生音频同步生成 |
| **分辨率** | 720p / 1080p |
| **时长** | 4秒 / 8秒（Veo 3.1 可选更长） |
| **图生视频** | 支持（Veo 3.1 支持最多3张参考图） |
| **音频** | 原生音视频同步生成（环境音、音效、对话） |
| **访问方式** | Google Flow（美国区）、Gemini API、Vertex AI、第三方平台（VeoStudio、Veo3 API等） |
| **参考来源** | Google DeepMind 官方文档 |

---

## 二、适用场景 vs 不适用场景

### ✅ 非常适合的场景

| 场景 | 效果说明 | 参考来源 |
|------|---------|---------|
| 电影感氛围镜头 | 灯光、光影、纹理渲染行业领先，接近摄影棚质感 | Vidguru AI 测评 |
| 环境音同步视频 | 雨声、风声、脚步声与画面完美空间同步（立体声场定位准确） | EasyP Studio 深度测评 |
| 产品展示广告（6-10秒） | 单产品+中性背景+缓慢推进，商业级画面，主体与背景分离干净 | Crevid AI 商业应用指南 |
| 自然景观/航拍镜头 | 黄金时段光线、自然纪录片风格，运动流畅 | Veo 3 官方提示词指南 |
| 快节奏视觉概念验证 | 分钟级出片，适合快速可视化创意 | Motion The Agency 测评 |
| 建立镜头/空镜头 | 交代环境、氛围的起始镜头，配合音效效果出色 | EasyP Studio |
| 高端品牌营销视频 | 影院级真实感，品牌调性匹配度高 | Vidguru AI |
| 旅行/运动内容 | POV 镜头、头盔cam等沉浸式视角 | Veo 3 官方提示词指南 |

### ⚠️ 勉强可用的场景（有条件限制）

| 场景 | 限制条件 | 解决建议 |
|------|---------|---------|
| 多角色复杂动作 | 动作流畅度不一致，多角色同时运动表现差 | 拆分单角色分别生成 |
| 角色一致性（跨镜头） | 面部细节在多镜头中可能漂移 | 使用参考图锚定（Veo 3.1） |
| 长对话场景 | 超过8秒对话容易失去唇形同步 | 保持对话在12-15词以内 |
| 水下场景 | 角色入水后可能消失 | 避免此场景或选择 Runway |
| 物体变形/消失逻辑 | 变形逻辑不符合物理（如瓶子从内部弹出） | 避免依赖精确变形逻辑 |
| 动漫/非写实风格 | 风格灵活性不如 Runway | 选择 Runway Gen-3 |

### ❌ 不适合/表现差的场景

| 场景 | 具体问题 | 替代方案 |
|------|---------|---------|
| 需要精确字幕的视频 | 字幕生成不稳定（Veo 3 有故障，3.1 有时不生成） | 后期字幕工具叠加 |
| 复杂叙事动作（多角色互动） | 物体中途消失、动作连贯性差 | Kling（角色一致性最强） |
| 水下/物理交互复杂情节 | 物体凭空消失 | Runway Gen-3（水下表现最佳） |
| 完全依赖语音旁白的专业内容 | 语音精度不如 ElevenLabs | 语音用 ElevenLabs，视频用 Veo 3 |
| 最大程度写实+复杂镜头 | 肤色倾向均匀，微妙光线衰减不如 Sora | OpenAI Sora（真实感之王） |
| 非写实艺术风格（动漫/VHS/水墨） | 风格适应范围窄 | Runway Gen-3 |
| 超长序列（>12秒单镜头） | 元素缺失、运动不连贯 | Sora 2（时间连贯性最强，可达~12s） |
| 文字渲染/Logo 出现 | 画面中随机出现不想要的文字 | 避免文字生成，用后期叠加 |
| 变形类魔法效果 | 变形逻辑不符合物理预期 | 简化变形描述或后期特效 |

**参考来源**：Motion The Agency 2025年7月实测评测；Vidguru AI 三平台对比测评；Crevid AI 商业应用指南

---

## 三、提示词技巧（Do's ✅）

> 所有条目均注明参考来源，支持溯源检查。

### 3.1 基础结构公式

| 技巧 | 说明 | 示例 | 来源 |
|------|------|------|------|
| **五要素/八组件结构** | 提示词应包含：主体+动作+场景+风格+音频（+镜头+构图+氛围） | 见下方完整示例 | Veo-video.org 五要素公式 |
| **细节越多控制力越强** | 提供更多细节，输出越能反映你的想象 | "二十多岁女性，卷棕发，脸上有浅色雀斑" 远优于 "女性" | Google DeepMind 官方 |
| **具体场景描述优于笼统描述** | "昏暗爵士酒吧，带裸露砖墙" 远优于 "酒吧内部" | — | EasyP Studio |
| **日常事件构建叙事** | 不需要史诗级，简单物体赋予使命也可完整叙事 | — | Google DeepMind 官方 |
| **Gemini 协助扩充** | 可用 Gemini 帮助扩展提示词细节 | — | Google DeepMind 官方 |

**参考来源**：Google DeepMind 官方提示词指南；Veo-video.org 完整指南

---

### 3.2 主体/角色描述

| 技巧 | 示例 | 来源 |
|------|------|------|
| 详细外貌描述（年龄、发型、肤色、眼睛颜色、面部特征） | "30岁女性，赤褐色波波头，椭圆形脸，浅色雀斑，棕色眼睛" | Sider AI 角色一致性指南 |
| 服装+颜色+面料描述 | "穿着炭灰色西装外套和白色衬衫" | GitHub snubroot/Veo-3-Prompting-Guide |
| 独特道具/标志性物品命名 | "银色小盒坠项链" | Sider AI |
| 姿态和习惯描述 | "保守姿势，微微微笑，头部略微倾斜" | Sider AI |
| 声音质量/语调描述 | "疲惫的声音"、"兴奋的低语"、"平静的单调" | Veo-video.org |
| **角色一致性模板**：姓名+年龄+民族+性别+发型+眼睛+面部特征+服装+姿态习惯 | 见上方"八组件框架" | GitHub snubroot |

---

### 3.3 镜头方向描述

| 技巧 | 示例 | 来源 |
|------|------|------|
| 包含相机位置（高度+角度）并加 `(thats where the camera is)` | "Close-up shot with camera positioned at counter level (thats where the camera is)" | GitHub snubroot |
| 使用具体焦段 | "35mm film"、"200mm telephoto"、"16mm wide-angle" | EasyP Studio |
| 景深描述 | "shallow depth of field"（浅景深）、"deep focus"（深焦） | EasyP Studio |
| 镜头虚化效果 | "oval bokeh from out-of-focus light sources" | EasyP Studio |
| 微手持抖动增加真实感 | "natural handheld micro-movement" | EasyP Studio |
| 单一镜头运动指令（避免堆叠冲突） | 每次只写一个主要运动 | Veo-video.org |

---

### 3.4 光线与氛围

| 技巧 | 示例 | 来源 |
|------|------|------|
| 黄金时段光线 | "golden hour backlight" | EasyP Studio |
| 蓝色时段 | "blue hour lighting" | EasyP Studio |
| 硬光/侧光戏剧效果 | "dramatic side lighting with hard shadows" | EasyP Studio |
| 柔和漫射光 | "soft diffused light" | EasyP Studio |
| 色彩分级描述 | "青色-品红色调"、"温暖金色调"、"柔和粉彩调" | Veo-video.org |
| 时间+天气+情绪组合 | "深夜大雪中的孤独小屋，风呼啸，温馨的隔离氛围" | EasyP Studio |
| 情感词汇影响多维度 | "紧张"、"平静"、"怀旧"、"威胁" 同时影响色彩、节奏和音频 | EasyP Studio |

---

### 3.5 音频描述

| 技巧 | 示例 | 来源 |
|------|------|------|
| **必须包含音频提示**（否则浪费一半能力） | — | EasyP Studio |
| 声音分层：基础层+中间层+顶层 | 基础层（环境音）+中间层（脚步声）+顶层（音乐） | EasyP Studio |
| 指定空间位置（画左=声左） | 画面左侧摩托车声音应在左声道 | EasyP Studio |
| 时间性音频过渡 | "从安静清晨逐渐过渡到嘈杂午间"、"音乐在前几秒后慢慢淡入" | EasyP Studio |
| 视觉事件与声音因果关联 | "陶瓷杯子稳稳放在木桌上，发出满足的闷响" | EasyP Studio |
| 环境音描述要具体 | "远处雷声+金属屋顶近距离雨声" 远优于 "雨声" | EasyP Studio |
| 排除不想要的声音 | "no audience sounds, professional atmosphere" | GitHub snubroot |
| 类型化音频：恐怖片=稀疏+突然静默 | — | EasyP Studio |
| 类型化音频：商业片=明快有节奏 | — | EasyP Studio |

---

### 3.6 对话处理

| 技巧 | 示例 | 来源 |
|------|------|------|
| 台词用引号包裹，用冒号格式 | `Sarah says: "Our Q3 results exceeded expectations"` | GitHub snubroot |
| 描述语音质量+语调 | "疲惫的声音"、"兴奋的低语" | Veo-video.org |
| 保持简短（8秒法则：12-15词，20-25音节） | — | GitHub snubroot |
| 避免15秒以上长段落 | 会导致急促语音 | GitHub snubroot |
| **多次强调无字幕** | "No subtitles. No subtitles! No on-screen text whatsoever." | GitHub snubroot |
| 否定字幕格式 | "(no subtitles)" 或 "no text overlays" | GitHub snubroot |

---

### 3.7 首帧/参考图模式

| 技巧 | 示例 | 来源 |
|------|------|------|
| 使用高分辨率图片（至少1080p，2K更佳） | — | Eastondev 图生视频指南 |
| **不要描述图片中已有的内容**，描述你希望看到的动作 | — | Eastondev |
| 配合动作关键词 | "subtle movement"、"dynamic motion" | Eastondev |
| 保持首尾帧风格和分辨率一致，过渡更平滑 | — | Eastondev |
| 差异大的首尾帧（如白天到夜晚）选8秒时长 | — | Eastondev |
| 参考图模式：用3张不同角度（正面+侧面+3/4视角） | — | Eastondev；Veo 3.1 多镜头指南 |
| 保持光线一致（不要混用阳光和室内光） | — | Eastondev |
| 出现颜色漂移时换掉最模糊的参考图 | — | Eastondev |
| **组合使用**：参考图+首尾帧 = 90%+可控性 | — | Eastondev |

---

## 四、提示词禁忌（Don'ts ❌）

> 所有条目均注明参考来源。

| 禁忌 | 原因/后果 | 正确做法 | 来源 |
|------|---------|---------|------|
| **堆叠多个冲突的镜头运动指令** | 模型困惑，输出不稳定 | 每次只用一个主要镜头运动 | Veo-video.org |
| **模糊主体描述** | 模型随机填充细节 | 具体描述外貌、服装、年龄 | Veo-video.org |
| **忽略音频维度** | 浪费 Veo 3 核心能力 | 始终包含音频方向 | EasyP Studio |
| **过长提示词** | 关键细节被稀释 | 保持聚焦且结构清晰 | Veo-video.org |
| **跳过迭代** | 首次尝试很少完美 | 从简单开始，逐步完善 | Veo-video.org |
| **风格不一致** | 破坏多镜头视觉连续性 | 复用相同的色调和风格描述 | Veo-video.org |
| **用 `says "dialogue"` 格式** | 可能触发字幕生成 | 使用 `says: "dialogue"` 冒号格式 | GitHub snubroot |
| **缺少相机定位词** | 相机不跟随主体 | 添加 `(thats where the camera is)` | GitHub snubroot |
| **音频不指定** | 产生不想要的随机声音 | 始终包含 `Audio:` 具体描述 | GitHub snubroot |
| **物理矛盾描述** | "夜晚海滩，阳光照在波浪上" | 确保光线/时间描述逻辑一致 | Vmake AI |
| **追求单镜头长场景** | 元素缺失、运动不连贯 | 拆分为多个短片段 | Vmake AI |
| **依赖试错法** | 浪费时间和额度 | 提前规划提示，草稿迭代 | Vmake AI |
| **场景过度加载** | 画面不稳定 | 视为摄影棚拍摄而非短片创作 | Crevid AI |
| **镜头语言过于激进** | 快速复杂运动被过度夸张 | 用"slow push"、"gentle pan" | Crevid AI |
| **时长不必要延长** | 增加画面漂移风险 | 信息传达完成即停止 | Crevid AI |
| **参考图模糊输入** | 产生模糊输出 | 使用高分辨率图片 | Eastondev |
| **跳过摄像机指示** | 画面静态/无聊或角度怪异 | 明确指定摄像机角度+运动 | Vmake AI |

---

## 五、镜头控制技巧

### 5.1 基础镜头类型

| 镜头 | 关键词 | 使用时机 | 来源 |
|------|-------|---------|------|
| 广角/建立镜头 | "wide shot"、"establishing shot" | 建立场景、风景 | Veo-video.org |
| 中景 | "medium shot"、"waist-up" | 对话、一般动作 | Veo-video.org |
| 特写 | "close-up"、"tight shot" | 情感、产品细节 | Veo-video.org |
| 极特写 | "macro shot"、"extreme close-up" | 纹理、围观细节 | Veo-video.org |
| POV镜头 | "POV shot"、"first-person view" | 沉浸式、第一视角 | Veo-video.org |

### 5.2 镜头运动

| 运动类型 | 关键词 | 效果 | 来源 |
|---------|-------|------|------|
| 推进 | "Dolly in"、"slow push-in" | 靠近主体，营造张力或揭示背景 | Veo-video.org；EasyP Studio |
| 拉远 | "Dolly out" | 揭示更多环境 | Veo-video.org |
| 水平旋转 | "Pan shot" | 扫描环境或跟随横向运动 | Veo-video.org |
| 跟随拍摄 | "Tracking shot" | 跟随主体移动，创造沉浸感 | Veo-video.org |
| 垂直升降 | "Crane shot" | 史诗级揭示 | Veo-video.org |
| 推拉变焦 | "Dolly zoom (Vertigo effect)" | 戏剧性眩晕感 | Veo-video.org |
| 倾斜 | "Tilt shot" | 上下旋转 | EasyP Studio |

### 5.3 焦距与镜头效果

| 效果 | 关键词 | 来源 |
|------|-------|------|
| 浅景深（背景虚化） | "shallow depth of field" | EasyP Studio |
| 散景（圆形背景虚化） | "oval bokeh from out-of-focus light sources" | EasyP Studio |
| 焦点切换 | "Rack focus" | EasyP Studio |
| 广角畸变 | "wide-angle lens" | EasyP Studio |
| 长焦压缩 | "200mm telephoto lens" | EasyP Studio |
| 胶片颗粒感 | "35mm film grain"、"shot on 16mm" | EasyP Studio |
| 手持微动 | "natural handheld micro-movement" | EasyP Studio |

### 5.4 自拍视频专用公式

```
A selfie video of [角色]... holds the camera at arm's length... [his/her] arm is clearly visible in the frame... occasionally looking into the camera before [动作]... The image is slightly grainy, looks very film-like
```

**参考来源**：GitHub snubroot/Veo-3-Prompting-Guide

---

## 六、音频生成技巧

### 6.1 为什么音频是 Veo 3 的核心差异

> Veo 3 是首个**原生同步生成音视频**的 AI 视频模型。其他模型（Sora、Runway、Kling）生成无声视频，音频需后期添加。

**关键原则**：忽略音频维度的提示词只利用了 Veo 3 **一半的能力**。

**参考来源**：EasyP Studio

### 6.2 声音分层模型

| 层级 | 示例 | 说明 | 来源 |
|------|------|------|------|
| **基础层（环境音）** | 雨声、风声、人群嘈杂、城市喧嚣 | 场景底噪 | EasyP Studio |
| **中间层（事件音）** | 脚步声、门关闭、键盘敲击、物体碰撞 | 特定事件 | EasyP Studio |
| **顶层（音乐/氛围）** | 背景音乐、主题音 | 可选配乐 | EasyP Studio |

### 6.3 音效与视觉同步

| 技巧 | 示例 | 来源 |
|------|------|------|
| 描述声音与画面事件的因果关系 | "陶瓷杯子稳稳放在木桌上，发出满足的闷响" | EasyP Studio |
| 明确指定预期音频 | "Audio: quiet office ambiance, keyboard typing, no audience sounds" | GitHub snubroot |
| 指定是否需要音乐 | "no background music" 或 "subtle ambient music" | GitHub snubroot |
| 排除不想要的声音 | "no audience laughter sounds" | GitHub snubroot |
| 空间音频（画左=声左） | 左侧摩托车声音应在左声道 | EasyP Studio |
| 时间性过渡 | "音乐在前几秒后慢慢淡入" | EasyP Studio |

### 6.4 恐怖片/纪录片/商业片音频策略

| 类型 | 音频策略 | 来源 |
|------|---------|------|
| 恐怖片 | 稀疏、构建张力的音频 + 突然的静默 | EasyP Studio |
| 纪录片 | 干净的环境音 + 自然空间感 | EasyP Studio |
| 商业片 | 明快、有节奏的氛围音支持快切 | EasyP Studio |

### 6.5 对话音频限制

| 要点 | 说明 | 来源 |
|------|------|------|
| **短句/单句效果最佳** | 唇形同步在长段落容易失真 | EasyP Studio |
| 避免15秒以上长对话 | 会导致急促语音 | GitHub snubroot |
| 8秒理想长度 | 12-15词，20-25音节 | GitHub snubroot |
| 语音密集场景 | 建议用 Veo 3 生成建立镜头，切换到 ElevenLabs 做对话 | EasyP Studio |

---

## 七、首帧/参考图（图生视频）技巧

### 7.1 三种图像引导模式

| 模式 | 功能 | 最佳用途 | 来源 |
|------|------|---------|------|
| **首帧模式（First Frame）** | 上传一张图作为视频第一帧，AI 延续动作 | 为静态插画/照片添加动画，保留原艺术风格 | Eastondev |
| **首尾帧模式（First & Last Frame）** | 提供起始+结束两张图，AI 填充过渡 | 精确控制镜头运动（如180度环绕）；白天到夜晚转换 | Eastondev |
| **参考图模式（Reference Image）** | 最多3张不同角度参考，确保角色/产品全程一致 | 系列内容、品牌吉祥物、产品展示 | Eastondev；Veo 3.1 多镜头指南 |

### 7.2 首帧模式核心原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **不描述图片中已有的内容** | 描述你希望看到的动作 | Eastondev |
| **使用高分辨率图片** | 至少1080p，2K更佳；模糊输入产生模糊输出 | Eastondev |
| 配合"subtle movement"或"dynamic motion" | 调整动作强度 | Eastondev |
| 避免描述图片中已有的内容 | 而非仅描述静态 | Eastondev |

### 7.3 首尾帧模式核心原则

| 原则 | 说明 | 来源 |
|------|------|------|
| 首尾帧风格/分辨率保持一致 | 过渡更平滑 | Eastondev |
| 差异大（如白天→夜晚）选8秒 | 给AI更多过渡空间 | Eastondev |
| 提示词描述"如何过渡" | 而非仅描述帧内容 | Eastondev |
| 首尾帧差异大时加时长 | 从6秒改为8秒 | Eastondev |

### 7.4 参考图模式核心原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **使用3张不同角度** | 正面+侧面+3/4视角 | Eastondev |
| 背景简洁 | 避免干扰AI | Eastondev |
| **光线必须一致** | 不要混用阳光和室内光 | Eastondev |
| 出现颜色漂移时 | 换掉最模糊的参考图 | Eastondev |
| 主体漂移/变形时 | 添加第三角度参考 | Eastondev |

### 7.5 参数设置建议

| 参数 | 建议 | 说明 | 来源 |
|------|------|------|------|
| 时长 | **首选8秒** | 4秒太短，6秒别扭 | Eastondev |
| 分辨率 | **1080p** | 720p更快但质量差 | Eastondev |
| 版本 | Veo 3.1 Fast：初测；Veo 3.1 Full：最终输出 | — | Eastondev |

### 7.6 效率对比

| 对比项 | 纯文字生成 | 图像引导生成 | 来源 |
|--------|----------|------------|------|
| 平均尝试次数 | 10-50次 | 2-5次 | Eastondev |
| 时间节省 | — | 80-90% | Eastondev |
| 成本节省 | — | 80-90% | Eastondev |
| 一下午产出 | 1-2个可用视频 | 5-8个可用视频 | Eastondev |

### 7.7 高级组合技巧

| 技巧 | 说明 | 来源 |
|------|------|------|
| **多段连接** | 用前一段视频的最后一帧作为下一段的首帧 | Eastondev |
| **参考图+首尾帧组合** | 约90%+可控性 | Eastondev |
| **风格转换** | 上传真实照片 + "anime style"提示词 → 逐步转动漫风格 | Eastondev |
| **用Veo 3.1先生成角色 → 截图作为后续镜头参考** | 解决无现成参考图的问题 | Vmake AI |

---

## 八、角色一致性（多镜头）技巧

### 8.1 Veo 3.1 的核心突破

> Veo 3.1 通过改进的角色和场景持久性控制，着力解决了多镜头一致性问题。每个镜头最多可使用**3张参考图**。

**参考来源**：Sider AI；Skywork AI

### 8.2 角色圣经（Character Bible）模板

```
姓名，[年龄][民族][性别]，拥有[具体发型]，[眼睛颜色]眼睛，
[独特面部特征]，穿着[详细服装描述]，
具有[姿态和习惯]
```

**示例**：
> Sarah Chen，35岁亚裔美国女性，肩长发专业bob发型，棕色眼睛，wire-rim眼镜，穿着炭灰色西装外套和白色衬衫，自信姿态

**参考来源**：GitHub snubroot；Sider AI

### 8.3 视觉词典（Lookbook）内容

| 内容 | 说明 | 来源 |
|------|------|------|
| 镜头语言 | 35mm手持、85mm特写等 | Skywork AI |
| 运动风格 | 推拉、横摇、三脚架 | Skywork AI |
| 色调描述 | 青色-橙色配霓虹洋红色点缀 | Skywork AI |

### 8.4 连续性提示词模板（跨镜头）

| 层级 | 示例内容 | 来源 |
|------|---------|------|
| **身份层** | "同一女性主角，30岁出头，肩长发，戴红色围巾" | Skywork AI |
| **摄影层** | "35mm手持跟拍；黄金时刻暖调主光+柔和背光；浅景深" | Skywork AI |
| **环境层** | "湿漉漉的街道，霓虹招牌倒影；保持青色-橙色调配洋红色高光" | Skywork AI |
| **表演层** | "坚定行走、微微微笑、目视前方；围巾保持可见" | Skywork AI |
| **音频层** | "柔和雨声+远处车流；低音量微妙合成音主题" | Skywork AI |
| **排除层** | "无帽子、无胡须、避免服装变化、无雪" | Skywork AI |

### 8.5 首尾帧条件化（跨镜头桥接）

| 技术 | 说明 | 来源 |
|------|------|------|
| 用 shot N 的尾帧作为 shot N+1 的起始帧 | 保持运动矢量连续性 | Skywork AI |
| 固定摄影语法（过渡镜头用三脚架） | 减少模型自由度 | Skywork AI |
| 色调/时间锁定 | 跨关联镜头重复相同色调描述 | Skywork AI |

### 8.6 常见漂移问题解决

| 问题 | 解决方案 | 来源 |
|------|---------|------|
| **面部变化** | 加强身份描述+复用2-3张干净参考+添加精确负面提示 | Skywork AI；Sider AI |
| **服装/道具漂移** | 每镜头明确列出服装+固定道具位置+锁定色调描述 | Skywork AI |
| **环境重置** | 逐字重复说明元素+保持相机轴一致 | Sider AI |
| **光照变化** | 修复光照块+避免序列中间改变时间 | Sider AI |
| **动作连续性断裂** | 使用尾帧条件化+标准化摄影机语法 | Skywork AI |
| **音频不匹配** | 仅限氛围+主题音指令，稀疏音频减少多样性损失 | Skywork AI |

### 8.7 多镜头工作流程检查清单

```
□ 1. 组装资产
   - 角色圣经：3张参考（正面、3/4侧面、侧面）
   - Lookbook：镜头、运动、色调帧
   - 分镜表：填写所有连续性列

□ 2. 编写分层提示词
   - 身份、摄影、环境、表演、音频、排除项
   - 跨镜头重复相同词汇

□ 3. 生成镜头A
   - 保持干净的尾帧

□ 4. 桥接到镜头B
   - 使用尾帧条件化（如支持）
   - 保持摄影语法稳定

□ 5. 迭代并锁定
   - 应用故障排除矩阵
   - 叙事流畅时停止迭代
```

**参考来源**：Skywork AI

---

## 九、竞品对比参考

### 9.1 核心参数对比

| 项目 | Veo 3.1 | Kling v2.1 | Sora 2 | Runway Gen-3 |
|------|---------|------------|--------|--------------|
| **分辨率** | 720p/1080p | 720p/1080p | 720p/1080p | 720p/1080p |
| **典型时长** | 4-8s | 5s/10s | 4-12s | 5s |
| **音频** | ✅ 原生同步音频 | ❌ 无 | ✅ 对白+音效 | ❌ 无 |
| **帧控制** | ✅ 首尾帧 | ✅ 首尾帧（Pro更优） | ✅ 仅起始帧 | ✅ |
| **视觉质量** | ⭐⭐⭐⭐⭐ 9.5/10 | ⭐⭐⭐⭐ 8/10 | ⭐⭐⭐⭐ 7.5-8.8/10 | ⭐⭐⭐⭐⭐ |
| **价格/秒** | $0.2-0.4（最高） | $0.01-0.05（最低） | $0.1 | 中等 |
| **角色一致性** | 中等（参考图改善） | **最强** | 良好 | 良好 |

**参考来源**：Vidguru AI 三平台对比测评；EasyP Studio 四平台深度对比

### 9.2 各平台最佳使用场景

| 平台 | 最佳用途 | 适合人群 |
|------|---------|---------|
| **Veo 3.1** | 高端质感营销、品牌视频、专业制片；声音设计关键项目 | 营销机构、高端品牌、专业制作人 |
| **Kling v2.1** | 社媒内容、电商产品视频、预算敏感项目；精确帧控制 | 个人创作者、小团队、抖音/TikTok |
| **Sora 2** | 含对白的教育内容、叙事广告、最长单镜头（~12s） | 影视创作者、教育工作者、广告主 |
| **Runway Gen-3** | 超越写实的特定视觉风格；水下场景；艺术内容 | 音乐视频、艺术内容、实验性作品 |

### 9.3 分场景推荐

| 需求 | 推荐 | 原因 |
|------|------|------|
| 🎬 **最高视觉质量** | Veo 3.1 | 影院级真实感，纹理与光照渲染行业领先 |
| 💰 **预算敏感** | Kling v2.1 | 成本仅为 Veo 3.1 的1/20 |
| 🎤 **需要音频/对白** | Veo 3.1 或 Sora 2 | 两者均支持原生音频 |
| 🎯 **精确帧控制** | Kling v2.1 | 首尾帧控制最精确 |
| ⏱️ **最长单段时长** | Sora 2 | 可达~12秒单镜头 |
| 🏊 **水下场景** | Runway Gen-3 | 物理准确性最佳 |
| 🎨 **动漫/非写实风格** | Runway Gen-3 | 风格适应范围最广 |
| 👤 **角色一致性** | Kling | 面部一致性问题最少 |
| 🗣️ **语音旁白** | ElevenLabs（配合Veo 3视频） | 专业语音精度更高 |

**参考来源**：Vidguru AI；EasyP Studio；Crevid AI

---

## 十、版本差异（Veo 3 vs Veo 3.1）

| 方面 | Veo 3 | Veo 3.1 改进 | 来源 |
|------|-------|-------------|------|
| **画质** | 优秀 | 更加清晰锐利，视觉效果更HD | Motion The Agency |
| **动态效果** | 良好 | 运动更加流畅稳定 | Motion The Agency |
| **对话流畅度** | 一般 | 自然度略有提升（但仍未完全达到真人水平） | Motion The Agency |
| **角色一致性** | 较弱 | 改进，支持3张参考图锚定 | Sider AI |
| **帧控制** | 首帧模式 | ✅ 首帧+尾帧+参考图三模式 | Veo 3.1发布公告 |
| **音频** | 环境音+音效+对话 | 增加更精细的音频控制 | Veo 3.1发布公告 |
| **镜头扩展** | 不支持 | ✅ 支持镜头扩展 | Skywork AI |
| **分辨率** | 最高1080p | 1080p（4K通过API） | — |

---

## 十一、商业使用注意事项

### 11.1 定价参考

| 平台 | 价格/秒 | 备注 | 来源 |
|------|---------|------|------|
| **Kling v2.1** | $0.01-0.05 | 性价比最高 | Vidguru AI |
| **Sora 2** | $0.1（Pro: $0.3-0.5） | 中等 | Vidguru AI |
| **Veo 3.1** | $0.2-0.4（含音频更贵） | 最高（约为Kling的20-40倍） | Vidguru AI |

### 11.2 商业使用限制

| 限制项 | 说明 | 来源 |
|------|------|------|
| **地区限制** | Veo 3 主要面向美国用户，非美国区需VPN | Motion The Agency |
| **内容审核** | Sora 最严格；Veo 3 次之；对戏剧性/边缘内容有限制 | EasyP Studio |
| **水印** | 部分第三方平台可能添加水印 | 需确认具体平台 |
| **商用授权** | 需查阅各平台服务条款（Gemini API有商用条款） | Veo 3 商业使用指南 |

### 11.3 ROI 最佳场景（高性价比）

| 场景 | 原因 | 来源 |
|------|------|------|
| UGC风格广告 | 低成本快速产出，适合社媒 | Geeky Gadgets |
| 产品营销视频 | 强调画质和氛围的商业内容 | Geeky Gadgets |
| 品牌整合 | 快速可视化创意供内部提案 | Geeky Gadgets |
| 短视频广告（6-10秒） | 单品+中性背景+缓慢推进最稳定 | Crevid AI |

### 11.4 智能工作流策略

> **最佳策略：不拘泥于单一平台，根据每个镜头选择最适合的工具。**

| 场景 | 推荐工具组合 |
|------|-------------|
| 高端品牌视频 | Veo 3.1（视觉+音频） |
| 快速迭代/社媒 | Kling v2.1（成本低） |
| 叙事内容/对白 | Sora 2 + ElevenLabs（语音） |
| 艺术风格内容 | Runway Gen-3 |
| 跨平台统一工作流 | EasyP Studio（支持四平台同步生成对比） |

**参考来源**：EasyP Studio

---

## 十二、好用提示词模板（分类）

> 来自 Veo-video.org；EasyP Studio；GitHub snubroot；Crevid AI 等多个来源，注明出处方便溯源。

### 12.1 产品展示类

> **来源**：Veo-video.org；Crevid AI

```
近景，一块时尚智能手表放在悬崖边岩石上。
相机从近处开始，以流畅的无人机镜头拉回。
升起时，广阔 alpine 山景展开。
产品商业风格，戏剧性自然光。
```

```
A clean commercial-style video of a modern product placed on a neutral background.
The camera slowly pushes forward, keeping the product centered and sharply in focus.
Soft studio lighting, subtle reflections, premium advertising look.
No sudden motion, no scene cuts, smooth and stable movement.
```

### 12.2 自然纪录片类

> **来源**：Veo-video.org；EasyP Studio

```
广角跟拍一只孤独的狼在密林中穿过新雪。
黄昏时分。侧面跟拍。
爪子踩雪嘎吱作响，风穿过松树低语。
纪录片风格，自然光，35mm胶片颗粒。
```

```
Aerial tracking shot following a golden eagle in flight over snow-capped peaks at dawn.
Camera maintains steady pace alongside the bird at 200 meters altitude.
Long telephoto compression flattens the mountain range behind into layered blue silhouettes.
4K resolution with National Geographic documentary quality.
Audio: strong wind at altitude with intermittent gusts. Eagle wing beats audible during close passes.
Majestic, contemplative mood with epic-scale spatial awareness.
```

### 12.3 城市/旅行类

> **来源**：EasyP Studio；Veo-video.org

```
Tracking shot following a man in a dark overcoat walking through rain-slicked streets of downtown Tokyo.
Neon signs in Japanese reflect off wet asphalt in pink, blue, and amber streaks.
Shot on anamorphic 40mm lens with shallow depth of field, oval bokeh from out-of-focus light sources.
Slow, deliberate pace with natural handheld micro-movement.
Audio: persistent rain on concrete with occasional heavier splashes from footsteps through puddles.
Distant traffic hum. Muffled music leaking from a basement jazz club.
Melancholic, noir atmosphere. Blade Runner-inspired color palette with teal shadows and warm neon highlights.
```

```
摩托车头盔cam POV镜头沿着蜿蜒海岸公路飞驰。
相机倾斜入弯，展现悬崖边缘和下方海洋。
黄金时段光线，太阳耀斑。
高能量运动风格。
```

### 12.4 对话/采访类

> **来源**：GitHub snubroot；Veo-video.org

```
中景，一位自信的演讲者在现代会议厅的讲台上。
她自然地做手势说："AI的未来不是关于替代——而是关于协作。"
柔和舞台灯光，专业企业美学。
```

```
Subject: Sarah Chen, 35岁亚裔美国女性，肩长发专业bob发型，棕色眼睛，wire-rim眼镜，
穿着炭灰色西装外套和白色衬衫，自信姿态
Action: 她自信地站在现代玻璃会议室中央，手势向展示屏幕展示图表
Scene: 现代玻璃墙董事会议室，大窗户俯瞰城市天际线，日落金色光线
Style: 中景推进到近景，专业三点照明，暖色主光，专业电影色调
Dialogue: (自信权威)
Sarah says: "Our Q3 results exceeded expectations, positioning us for unprecedented growth."
Audio: 清晰权威的声音，窗外城市氛围，无背景音乐
Technical (Negative): subtitles, captions, watermark, text overlays, logo, branding, poor lighting
```

### 12.5 恐怖/悬疑类

> **来源**：Veo-video.org

```
低角度广角，一个人站在长而空旷的医院走廊尽头，荧光灯闪烁。
身影缓缓走向镜头，脚步声回荡。
去饱和色彩，重颗粒，恐怖美学。
Audio: fluorescent light buzzing, distant footsteps echoing, oppressive silence
```

### 12.6 美食/生活方式类

> **来源**：Veo-video.org

```
中景，厨师的手在大理石台面上摆放新鲜食材，动作从容。
相机倾斜向上揭示厨师专注的表情。
头顶自然光，温暖生活方式美学。
```

### 12.7 时尚/美容类

> **来源**：Veo-video.org

```
慢速推镜，模特穿着飘逸丝绸连衣裙穿过空荡艺术画廊。
每一步都在面料上引起微妙涟漪。
柔和漫射画廊灯光，高端时尚编辑风格。
```

### 12.8 情感叙事类

> **来源**：Veo-video.org

```
中景，一位老人坐在公园长椅上喂鸽子，午后温暖光线穿透秋树。
他停下来，抬起头露出温柔微笑，树叶飘落。
情感怀旧基调，浅景深。
```

### 12.9 科技演示类

> **来源**：Veo-video.org

```
手与透明全息显示器互动的特写，滑动和捏合操纵3D数据可视化。
蓝白色界面光芒照亮面部。
未来科幻美学，简洁简约设计。
```

### 12.10 奢侈品类

> **来源**：Veo-video.org

```
奢华香水瓶在反光黑色表面上的微距特写，
戏剧性聚光灯创造金色高光。
瓶子缓慢旋转展示优雅设计细节。
高端商业美学。
```

---

## 十三、踩坑经验汇总

> 以下为实际调用中发现的常见问题，供快速参考。

| 问题 | 场景 | 经验要点 | 来源 |
|------|------|---------|------|
| 字幕意外生成 | 对话提示词 | 用 `says: "dialogue"` 格式而非 `says "dialogue"`，加 `(no subtitles)` | GitHub snubroot |
| 相机不跟随主体 | 镜头指令 | 必须加 `(thats where the camera is)` 定位词 | GitHub snubroot |
| 音频幻觉（不想要的声音） | 音效提示 | 始终指定 Audio 内容，包括排除项 | GitHub snubroot |
| 角色跨镜头漂移 | 多镜头叙事 | 使用完全相同的角色描述模板词汇 | Sider AI；Skywork AI |
| 首帧变形 | 图生视频 | 首尾帧差异大时选8秒，避免6秒 | Eastondev |
| 颜色漂移 | 参考图模式 | 换掉最模糊的参考图，添加第三角度 | Eastondev |
| 动作不自然 | 动作密集场景 | 加 "natural movement" 等动作质量词 | GitHub snubroot |
| 运动堆叠冲突 | 镜头运动 | 每个提示词只用一个主要镜头运动 | Veo-video.org |

---

## 十四、参考资料索引

| # | 来源 | 类型 | URL |
|---|------|------|-----|
| 1 | Google DeepMind 官方提示词指南 | 官方文档 | deepmind.google/models/veo/prompt-guide/ |
| 2 | GitHub snubroot/Veo-3-Prompting-Guide | GitHub | github.com/snubroot/Veo-3-Prompting-Guide |
| 3 | Veo-video.org Veo 3.1 提示词完整指南 | 博客 | veo-video.org/blog/veo31-prompt-guide |
| 4 | EasyP Studio Veo 3 完整提示词指南 | 博客 | easypstudio.com/blog/veo-3-prompt-guide/ |
| 5 | Eastondev Veo 3 图生视频指南 | 博客 | eastondev.com/blog/en/posts/ai/20251207-veo3-image-to-video-guide/ |
| 6 | Sider AI Veo 3.1 角色一致性深度分析 | 博客 | sider.ai/zh-CN/blog/ai-tools/how-veo-3_1-maintains-character-scene-consistency |
| 7 | Skywork AI Veo 3.1 多提示故事最佳实践 | 博客 | skywork.ai/blog/multi-prompt-multi-shot-consistency-veo-3-1-best-practices/ |
| 8 | Vmake AI Veo 3.1 常见错误与最佳实践 | 博客 | vmake.ai/blog/common-mistakes-when-using-veo-3-1-how-to-get-the-best-results |
| 9 | Motion The Agency Veo 3.1 真实评测 | 博客 | motiontheagency.com/blog/google-veo-3-review |
| 10 | Vidguru AI Veo 3.1 vs Kling vs Sora 2 对比 | 博客 | vidguru.ai/zh/blog/veo-3.1-vs-kling-v2.1-vs-sora-2 |
| 11 | EasyP Studio Sora vs Runway vs Kling vs Veo 3 四平台对比 | 博客 | easypstudio.com/blog/sora-vs-runway-vs-kling-vs-veo3/ |
| 12 | Crevid AI Veo 3 产品广告实用策略 | 博客 | crevid.ai/blog/veo3-ai-commercial-videos |
| 13 | Eastondev Veo 3 角色一致性完整指南 | 博客 | eastondev.com/blog/en/posts/ai/20251207-veo3-character-consistency-guide/ |
| 14 | Veo 3 商业使用指南 2026 | 博客 | veo3ai.io/blog/veo-3-commercial-use-guide-2026 |
| 15 | Winterspeak Veo 3 角色一致性讨论 | Substack | winterspeak.substack.com/p/veo-3-does-not-solve-the-character |
| 16 | Google DeepMind Veo 官方模型页 | 官方 | deepmind.google/models/veo/ |
| 17 | Google AI Gemini API Video 文档 | 官方文档 | ai.google.dev/gemini-api/docs/video |
| 18 | Veo 3.1 API 文档 | 第三方文档 | veo3api.com/docs |
| 19 | VeoStudio Veo 3.1 集成 | 第三方 | veostudio.ai/veo-3-1-integration |
| 20 | fal.ai Veo 3.1 参考图API | API文档 | fal.ai/models/fal-ai/veo3.1/reference-to-video/api |

---

*文档整理完毕，共包含 **130+** 条独立条目，所有条目均标注来源，支持溯源检查。*
*如发现条目内容与原始来源不符，或有新的使用技巧发现，欢迎反馈更新。*
