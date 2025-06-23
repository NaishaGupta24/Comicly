
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import BaseTool
import google.generativeai as genai
from diffusers import StableDiffusionPipeline
from PIL import Image, ImageDraw, ImageFont
import torch, textwrap, json, os, urllib.request, tempfile
from glob import glob

# GEMINI setup
genai.configure(api_key="GEMINI_API_KEY")

# Font setup
font_path = os.path.join(tempfile.gettempdir(), "ComicNeue-Regular.ttf")
if not os.path.exists(font_path):
    urllib.request.urlretrieve(
        "https://github.com/google/fonts/raw/main/ofl/comicneue/ComicNeue-Regular.ttf", font_path
    )
comic_font = ImageFont.truetype(font_path, 28)

# Load SD model
pipe = StableDiffusionPipeline.from_pretrained(
    "dreamlike-art/dreamlike-diffusion-1.0",
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
).to("cuda")
pipe.enable_attention_slicing()
pipe.enable_model_cpu_offload()
pipe.enable_vae_slicing()

# 🛠️ WriteStoryTool
import re

class WriteStoryTool(BaseTool):
    def __init__(self):
        super().__init__(name="write_story", description="Writes comic panel scripts.")

    def run(self, inputs: dict):
        product = inputs["product"]
        audience = inputs.get("audience") or "general"
        n = inputs["num_panels"]

        prompt = f"""
Write a {n}-panel comic for the product '{product}' targeting {audience}.
Use witty, casual, funny tone.
Output as JSON: [{{"scene": "...", "dialogue": "..."}}]
No markdown, no intro, just valid JSON.
"""

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Debug print if output is not clean
        if not text.startswith("["):
            print("⚠ Gemini response not starting with JSON array:\n", text)

        # Try cleaning JSON if Gemini adds extras
        try:
            # Remove anything before the first [
            json_str = re.search(r"\[.*\]", text, re.DOTALL).group()
            story = json.loads(json_str)
        except Exception as e:
            print("❌ JSON parsing failed:", e)
            raise e

        return {"story": story}


# 🎨 GeneratePanelTool
class GeneratePanelTool(BaseTool):
    def __init__(self):
        super().__init__(name="generate_panels", description="Generates images for panels.")

    def run(self, inputs: dict):
        story = inputs["story"]
        num = len(story)
        result = []
        for i, panel in enumerate(story):
            prompt = (
                f"{panel['scene']},anime style, cute characters, bold outline, 2D"
            )
            negative_prompt = "realistic, text, watermark, horror, dark"
            generator = torch.Generator("cuda").manual_seed(42 + i)
            try:
                image = pipe(prompt, negative_prompt=negative_prompt,
                             num_inference_steps=40, guidance_scale=7.0,
                             generator=generator).images[0]
                path = f"panel_{i+1}.png"
                image.save(path)
            except Exception as e:
                print(f"[⚠] Failed panel {i+1}: {e}")
                blank = Image.new("RGB", (580, 540), "white")
                path = f"panel_{i+1}_blank.png"
                blank.save(path)
            result.append({"image": path, "dialogue": panel["dialogue"]})
        return {"panels": result}

# 🧩 LayoutComicTool
class LayoutComicTool(BaseTool):
    def __init__(self):
        super().__init__(name="layout_comic", description="Combines panels into final comic")

    def run(self, inputs: dict):
        panels, product = inputs["panels"], inputs["product"]
        rows = (len(panels) + 1) // 2
        final = Image.new("RGB", (1200, rows * 600 + 160), "white")
        draw = ImageDraw.Draw(final)

        draw.rectangle([0, 0, 1200, 100], fill="black")
        draw.text((30, 30), f"{product.upper()} ADVENTURE!", fill="white", font=comic_font)

        for i, panel in enumerate(panels):
            x, y = (i % 2) * 600, (i // 2) * 566 + 100
            img = Image.open(panel["image"]).resize((580, 540))
            final.paste(img, (x + 10, y + 10))
            dialog = textwrap.fill(panel["dialogue"], 30)
            w, h = draw.multiline_textbbox((0, 0), dialog, font=comic_font)[2:]
            px, py = x + 30, y + 400
            draw.rectangle([px, py, px + w + 30, py + h + 30], fill="white", outline="black", width=3)
            draw.multiline_text((px + 15, py + 15), dialog, font=comic_font, fill="black")
            draw.polygon([(px+90, py+h+30), (px+110, py+h+30), (px+100, py+h+50)], fill="white", outline="black")

        tagline = panels[-1]["dialogue"] if panels else "BUY NOW!"
        draw.rectangle([0, rows * 600 + 100, 1200, rows * 600 + 160], fill="#e67e22")
        draw.text((40, rows * 600 + 110), tagline.upper(), fill="white", font=comic_font)

        path = f"{product.lower()}_comic.png"
        final.save(path)
        return {"final_comic": path}

# ✅ Main controller
# 🚀 Main controller
def run_comicai():
    # 📥 User inputs
    product = input("📦 Product to promote: ").strip()
    audience = input("🎯 Target audience: ").strip()
    num_panels = int(input("🧩 Number of panels (4/6/8): ").strip())

    shared_data = {
        "product": product,
        "audience": audience,
        "num_panels": num_panels
    }

    # Agents
    story_agent = LlmAgent(
        name="StoryAgent",
        model="gemini-1.5-flash",
        instruction="Generate comic script",
        tools=[WriteStoryTool()]
    )

    panel_agent = LlmAgent(
        name="PanelAgent",
        model="gemini-1.5-flash",
        instruction="Generate panel illustrations",
        tools=[GeneratePanelTool()]
    )

    layout_agent = LlmAgent(
        name="LayoutAgent",
        model="gemini-1.5-flash",
        instruction="Assemble comic layout",
        tools=[LayoutComicTool()]
    )

    # ✅ Tool execution instead of agent.run()
    print("✍ Generating story...")
    story_out = story_agent.tools[0].run(shared_data)
    shared_data.update(story_out)

    print("🎨 Generating panels...")
    panel_out = panel_agent.tools[0].run(shared_data)
    shared_data.update(panel_out)

    # Feedback: retry blank panels
    retry_needed = any("blank" in p["image"] for p in panel_out["panels"])
    if retry_needed:
        print("🔁 Some panels failed. Retrying with minor prompt tweak...")
        shared_data["story"] = [
            {"scene": s["scene"] + " vibrant scenery", "dialogue": s["dialogue"]}
            for s in shared_data["story"]
        ]
        panel_out = panel_agent.tools[0].run(shared_data)
        shared_data.update(panel_out)

    print("🧩 Assembling final comic...")
    result = layout_agent.tools[0].run(shared_data)

    print("✅ Comic saved at:", result["final_comic"])

    try:
        from google.colab import files
        files.download(result["final_comic"])
    except:
        pass


# 🚀 Run
run_comicai()