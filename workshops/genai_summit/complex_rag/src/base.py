import os
import yaml
import base64
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_models import ChatOllama
from IPython.display import display, HTML
from langchain_community.llms.sambanova import SambaStudio, Sambaverse
from langchain_community.embeddings.sambanova import SambaStudioEmbeddings
from langchain_core.prompts import load_prompt
import nest_asyncio
from langchain_core.runnables.graph import CurveStyle, NodeColors, MermaidDrawMethod
import dotenv

dotenv.load_dotenv()

class BaseComponents:

    def __init__(self, configs, prompts_path) -> None:

        self.configs = configs
        self.prompts_path = prompts_path

    @staticmethod
    def load_config(filename: str) -> dict:
        """_summary_

        Args:
            filename (str): filepath of config yaml file

        Returns:
            dict: config dictionary
        """

        try:
            with open(filename, "r") as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            print("No YAML file found.")
            return None
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file: {e}")

    def load_embedding_model(self):
        embeddings = self.vectordb.load_embedding_model(type=self.embedding_model_info) 
        return embeddings  

    # def init_llm(self): #TODO: switch to CoE when Llama 3 is available

    #     local_llm = 'llama3'
    #     self.llm = ChatOllama(model=local_llm, temperature=0)
    

    def init_llm(self): 

        if self.configs["api"] == "sambastudio":
                self.llm = SambaStudio(
                    streaming=True,
                    model_kwargs={
                            "max_tokens_to_generate": 2048,
                            "select_expert": "Meta-Llama-3-8B-Instruct",
                            "process_prompt": False
                        }
                )

        elif self.configs["api"] == "sambaverse":
            self.llm = Sambaverse(
                streaming=False,
                model_kwargs={
                    "do_sample": False,
                    "process_prompt": True,
                    "select_expert": "llama-2-70b-chat-hf",
                },
            )
        
        else:
            raise ValueError("Please enter sambastudio or sambaverse for api in config.yaml")

    def _format_docs(self, docs):
    
        return "\n\n".join(doc.page_content for doc in docs)

    def init_embeddings(self):

        self.embeddings = SambaStudioEmbeddings()
    
    def _display_image(self, image_bytes: bytes, width=256):
        decoded_img_bytes = base64.b64encode(image_bytes).decode('utf-8')
        html = f'<img src="data:image/png;base64,{decoded_img_bytes}" style="width: {width}px;" />'
        display(HTML(html))
    
    def display_graph(self, app):

        nest_asyncio.apply() # Required for Jupyter Notebook to run async functions

        img_bytes = app.get_graph().draw_mermaid_png(
        curve_style=CurveStyle.LINEAR,
        node_colors=NodeColors(start="#ffdfba", end="#baffc9", other="#fad7de"),
        wrap_label_n_words=9,
        output_file_path=None,
        draw_method=MermaidDrawMethod.PYPPETEER,
        background_color="white",
        padding=10
)

        self._display_image(img_bytes)

    def init_base_llm_chain(self):
        base_llm_prompt = load_prompt(os.path.join(self.prompts_path, "base_llm_prompt.yaml"))
        self.base_llm_chain = base_llm_prompt| self.llm | StrOutputParser()


    def llm_generation(self, state):
        
        print("---GENERATING FROM INTERNAL KNOWLEDGE---")
        question = state["question"]
        
        # RAG generation
        generation = self.base_llm_chain.invoke({"question": question})
        return {"question": question, "generation": generation}