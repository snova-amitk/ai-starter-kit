import json
import os
import re
import sys
from pprint import pprint
from typing import Any, Dict, List, Optional, Tuple, Type, Union

import streamlit as st
import yaml
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool, Tool
from pydantic import BaseModel, Field

current_dir = os.path.dirname(os.path.abspath(__file__))
kit_dir = os.path.abspath(os.path.join(current_dir, '..'))
repo_dir = os.path.abspath(os.path.join(kit_dir, '..'))
sys.path.append(kit_dir)
sys.path.append(repo_dir)

from utils.model_wrappers.api_gateway import APIGateway
from utils.visual.env_utils import get_wandb_key

load_dotenv(os.path.join(repo_dir, '.env'))
# Handle the WANDB_API_KEY resolution before importing weave
wandb_api_key = get_wandb_key()

# If WANDB_API_KEY is set, proceed with weave initialization
if wandb_api_key:
    import weave

    # Initialize Weave with your project name
    weave.init('sambanova_search_assistant')
else:
    print('WANDB_API_KEY is not set. Weave initialization skipped.')


CONFIG_PATH = os.path.join(kit_dir, 'config.yaml')

FUNCTION_CALLING_SYSTEM_PROMPT = """you are an helpful assistant and you have access to the following tools:

{tools}

You must always select one or more of the above tools and answer with only a list of JSON objects matching the following schema:

```json
[{{
  "tool": <name of the selected tool>,
  "tool_input": <parameters for the selected tool, matching the tool's JSON schema>
}}]
```

Think step by step
Do not call a tool if the input depends on another tool output that you do not have yet.
Do not try to answer until you get all the tools output, if you do not have an answer yet, you can continue calling tools until you do.
Your answer should be in the same language as the initial query.

"""  # noqa E501


# tool schema
class ConversationalResponse(BaseModel):
    (
        'Respond conversationally only if no other tools should be called for a given query, '
        'or if you have a final answer. response must be in the same language as the user query'
    )

    response: str = Field(
        ..., description='Conversational response to the user. must be in the same language as the user query'
    )


class FunctionCallingLlm:
    """
    function calling llm class
    """

    def __init__(
        self,
        tools: Optional[Union[StructuredTool, Tool, List[Union[StructuredTool, Tool]]]] = None,
        default_tool: Optional[Union[StructuredTool, Tool, Type[BaseModel]]] = None,
        system_prompt: Optional[str] = None,
        config_path: str = CONFIG_PATH,
    ) -> None:
        """
        Args:
            tools (Optional[Union[StructuredTool, Tool, List[Union[StructuredTool, Tool]]]]): The tools to use.
            default_tool (Optional[Union[StructuredTool, Tool, Type[BaseModel]]]): The default tool to use.
                defaults to ConversationalResponse
            system_prompt (Optional[str]): The system prompt to use. defaults to FUNCTION_CALLING_SYSTEM_PROMPT
            config_path (str): The path to the config file. defaults to CONFIG_PATH
        """
        configs = self.get_config_info(config_path)
        self.llm_info = configs[0]
        self.prod_mode = configs[1]
        self.llm = self.set_llm()
        if isinstance(tools, Tool) or isinstance(tools, StructuredTool):
            tools = [tools]
        self.tools = tools
        if system_prompt is None:
            self.system_prompt = FUNCTION_CALLING_SYSTEM_PROMPT
        if default_tool is None:
            default_tool = ConversationalResponse
        tools_schemas = self.get_tools_schemas(tools, default=default_tool)
        self.tools_schemas = '\n'.join([json.dumps(tool, indent=2) for tool in tools_schemas])

    def get_config_info(self, config_path: str) -> Tuple[Dict[str, Any], bool]:
        """
        Loads json config file
        """
        # Read config file
        with open(config_path, 'r') as yaml_file:
            config = yaml.safe_load(yaml_file)
        llm_info = config['llm']
        prod_mode = config['prod_mode']

        return (llm_info, prod_mode)

    def set_llm(self) -> BaseChatModel:
        """
        Set the LLM to use.
        sambastudio and sncloud endpoints implemented.
        """
        if self.prod_mode:
            sambanova_api_key = st.session_state.SAMBANOVA_API_KEY
        else:
            if 'SAMBANOVA_API_KEY' in st.session_state:
                sambanova_api_key = os.environ.get('SAMBANOVA_API_KEY') or st.session_state.SAMBANOVA_API_KEY
            else:
                sambanova_api_key = os.environ.get('SAMBANOVA_API_KEY')

        llm = APIGateway.load_chat(
            type=self.llm_info['api'],
            max_tokens=self.llm_info['max_tokens'],
            temperature=self.llm_info['temperature'],
            model=self.llm_info['model'],
            sambanova_api_key=sambanova_api_key,
        )
        return llm

    def get_tools_schemas(
        self,
        tools: Optional[Union[StructuredTool, Tool, List[Any]]] = None,
        default: Optional[Union[StructuredTool, Tool, Type[BaseModel]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get the tools schemas.
        Args:
            tools (Optional[Union[StructuredTool, Tool, list]]): The tools to use.
            default (Optional[Union[StructuredTool, Tool, Type[BaseModel]]]): The default tool to use.
        """
        if tools is None or isinstance(tools, list):
            pass
        elif isinstance(tools, Tool) or isinstance(tools, StructuredTool):
            tools = [tools]
        else:
            raise TypeError('tools must be a Tool or a list of Tools')

        tools_schemas = []
        if tools is not None:
            for tool in tools:
                tool_schema = tool.get_input_schema().schema()
                schema = {
                    'name': tool.name,
                    'description': tool_schema['description'],
                    'properties': tool_schema['properties'],
                }
                if 'required' in schema:
                    schema['required'] = tool_schema['required']
                tools_schemas.append(schema)

        if default is not None:
            if isinstance(default, Tool) or isinstance(default, StructuredTool):
                tool_schema = default.get_input_schema().schema()
            elif issubclass(default, BaseModel):
                tool_schema = default.schema()
            else:
                raise TypeError('default must be a Tool or a BaseModel')
            schema = {
                'name': tool_schema['title'],
                'description': tool_schema['description'],
                'properties': tool_schema['properties'],
            }
            if 'required' in schema:
                schema['required'] = tool_schema['required']
            tools_schemas.append(schema)

        return tools_schemas

    def execute(self, invoked_tools: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Given a list of tool executions the llm return as required
        execute them given the name with the mane in tools_map and the input arguments
        if there is only one tool call and it is default conversational one, the response is marked as final response

        Args:
            invoked_tools (List[dict]): The list of tool executions generated by the LLM.
        """
        if self.tools is not None:
            tools_map = {tool.name: tool for tool in self.tools}
        else:
            tools_map = {}
        tool_msg = "Tool '{name}'response: {response}"
        tools_msgs = []
        if len(invoked_tools) == 1 and invoked_tools[0]['tool'].lower() == 'conversationalresponse':
            final_answer = True
            return final_answer, [invoked_tools[0]['tool_input']['response']]
        for tool in invoked_tools:
            final_answer = False
            if tool['tool'].lower() != 'conversationalresponse':
                print(f"\n\n---\nTool {tool['tool'].lower()} invoked with input {tool['tool_input']}\n")
                response = tools_map[tool['tool'].lower()].invoke(tool['tool_input'])
                print(f'Tool response: {str(response)}\n---\n\n')
                tools_msgs.append(tool_msg.format(name=tool['tool'], response=str(response)))
        return final_answer, tools_msgs

    def jsonFinder(self, input_message: BaseMessage) -> Optional[str]:
        """
        find json structures ina  llm string response, if bad formatted using LLM to correct it

        Args:
            input_string (str): The string to find the json structure in.
        """
        json_pattern = re.compile(r'(\{.*\}|\[.*\])', re.DOTALL)
        # Find the first JSON structure in the string
        assert isinstance(input_message.content, str)
        json_match = json_pattern.search(input_message.content)
        if json_match:
            json_str = json_match.group(1)
            try:
                json.loads(json_str)
            except:
                json_correction_prompt = [
                    ('system', """You are a json format corrector tool"""),
                    (
                        'human',
                        """fix the following json file: {json}
                     do not provide any explanation only return the fixed json""",
                    ),
                ]
                json_correction_prompt_template = ChatPromptTemplate(json_correction_prompt)
                json_correction_chain = json_correction_prompt_template | self.llm | StrOutputParser()
                json_str = json_correction_chain.invoke({'json': json_str})
                print(f'Corrected json: {json_str}')
        else:
            # will assume is a conversational response given is not json formatted
            print('response is not json formatted assuming conversational response')
            dummy_json_response = [
                {'tool': 'ConversationalResponse', 'tool_input': {'response': input_message.content}}
            ]
            json_str = json.dumps(dummy_json_response)
        return json_str

    def function_call_llm(self, query: str, max_it: int = 5, debug: bool = False) -> str:
        """
        invocation method for function calling workflow

        Args:
            query (str): The query to execute.
            max_it (int, optional): The maximum number of iterations. Defaults to 5.
            debug (bool, optional): Whether to print debug information. Defaults to False.
        """
        function_calling_chat_template = ChatPromptTemplate.from_messages([('system', self.system_prompt)])
        history = function_calling_chat_template.format_prompt(tools=self.tools_schemas).to_messages()
        history.append(HumanMessage(query))
        tool_call_id = 0  # identification for each tool calling required to create ToolMessages

        for i in range(max_it):
            json_parsing_chain = RunnableLambda(self.jsonFinder) | JsonOutputParser()
            print(f'\n\n---\nCalling function calling LLM with prompt: \n{history}\n')
            llm_response = self.llm.invoke(history)
            print(f'\nFunction calling LLM response: \n{llm_response}\n---\n')
            parsed_tools_llm_response = json_parsing_chain.invoke(llm_response)
            history.append(llm_response)
            final_answer, tools_msgs = self.execute(parsed_tools_llm_response)
            if final_answer:  # if response was marked as final response in execution
                final_response = tools_msgs[0]
                if debug:
                    print('\n\n---\nFinal function calling LLM history: \n')
                    pprint(f'{history}')
                return final_response
            else:
                history.append(ToolMessage('\n'.join(tools_msgs), tool_call_id=tool_call_id))
                tool_call_id += 1

        raise Exception('not a final response yet', history)
