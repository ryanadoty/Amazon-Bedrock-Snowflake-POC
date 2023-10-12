import os
from dotenv import load_dotenv
import yaml
from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate
from langchain.sql_database import SQLDatabase
from langchain.chains.sql_database.prompt import PROMPT_SUFFIX, _postgres_prompt
from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from langchain.llms import Bedrock
from langchain.prompts.example_selector.semantic_similarity import (
    SemanticSimilarityExampleSelector,
)
from langchain.vectorstores import Chroma
from langchain_experimental.sql import SQLDatabaseChain

# Loading environment variables
load_dotenv()
# configuring your instance of Amazon bedrock, selecting the CLI profile, modelID, endpoint url and region.
llm = Bedrock(
    credentials_profile_name=os.getenv("profile_name"),
    model_id="amazon.titan-text-express-v1",
    endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com",
    region_name="us-east-1",
    verbose=True
)


# Executing the SQL database chain with the users question
def snowflake_answer(question):
    """
    This function collects all necessary information to execute the sql_db_chain and get an answer generated, taking
    a natural language question in and returning an answer and generated SQL query.
    :param question: The question the user passes in from the frontend
    :return: The final answer in natural langauge along with the generated SQL query.
    """
    snowflake_url = get_snowflake_uri()
    db = SQLDatabase.from_uri(snowflake_url, sample_rows_in_table_info=1, include_tables=["artists", "artworks"])

    # load examples for few-shot prompting
    examples = load_samples()

    sql_db_chain = load_few_shot_chain(llm, db, examples)
    answer = sql_db_chain(question)

    return answer["intermediate_steps"][1], answer["result"]


def get_snowflake_uri():
    # SQLAlchemy 2.0 reference: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html
    # URI format: postgresql+psycopg2://user:pwd@hostname:port/dbname
    """
    This function initiates the creation of the snowflake URL for use with the SQLDatbaseChain
    :return: The full snowflake URL
    """

    snowflake_account = os.getenv("snowflake_account")
    username = os.getenv("username")
    password = os.getenv("password")
    database = os.getenv("database")
    schema = os.getenv("schema")
    role = os.getenv("role")

    # Building the Snowflake URL to use with the DB_chain
    snowflake_url = f"snowflake://{username}:{password}@{snowflake_account}/{database}/{schema}?role={role}"
    return snowflake_url


def load_samples():
    """
    Load the sql examples for few-shot prompting examples
    :return: The sql samples in from the moma_examples.yaml file
    """
    sql_samples = None

    with open("Sampledata/moma_examples.yaml", "r") as stream:
        sql_samples = yaml.safe_load(stream)

    return sql_samples


def load_few_shot_chain(llm, db, examples):
    """

    :param llm: Large Language model you are using
    :param db: The Snowflake database URL
    :param examples: The samples loaded from your examples file.
    :return: The results from the SQLDatabaseChain
    """
    example_prompt = PromptTemplate(
        input_variables=["table_info", "input", "sql_cmd", "sql_result", "answer"],
        template=(
            "{table_info}\n\nQuestion: {input}\nSQLQuery: {sql_cmd}\nSQLResult:"
            " {sql_result}\nAnswer: {answer}"
        ),
    )

    local_embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    example_selector = SemanticSimilarityExampleSelector.from_examples(
        examples,
        local_embeddings,
        Chroma,
        k=min(3, len(examples)),
    )

    few_shot_prompt = FewShotPromptTemplate(
        example_selector=example_selector,
        example_prompt=example_prompt,
        prefix=_postgres_prompt + "Provide no preamble" + " Here are some examples:",
        suffix=PROMPT_SUFFIX,
        input_variables=["table_info", "input", "top_k"],
    )
    # Where the LLM, DB and prompts are all orchestrated to answer a user query.
    return SQLDatabaseChain.from_llm(
        llm,
        db,
        prompt=few_shot_prompt,
        use_query_checker=True,  # must be False for OpenAI model
        verbose=True,
        return_intermediate_steps=True,
    )

