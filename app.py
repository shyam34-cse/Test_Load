import shutil
import os
import time
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import base64
import logging

from flask import Flask, jsonify, url_for, flash
from flask import render_template, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
import tempfile
import pickle

import nltk
from huggingface_hub import logout
from nltk.tokenize import word_tokenize
from wordcloud import WordCloud
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from nltk.corpus import stopwords
from azure.identity import DefaultAzureCredential

from azure.storage.blob import BlobServiceClient, BlobClient, ContentSettings, BlobProperties
from azure.identity import ClientSecretCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

from langchain.chat_models import AzureChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain
from langchain_community.document_loaders import AzureBlobStorageFileLoader, PyPDFLoader, Docx2txtLoader, \
    UnstructuredExcelLoader, \
    AssemblyAIAudioTranscriptLoader, CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.chat_models import AzureChatOpenAI
from langchain_community.embeddings import AzureOpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.memory import ConversationBufferMemory

from langchain.chains import ConversationalRetrievalChain
# from langchain.agents import AgentType
# from langchain.agents import create_pandas_dataframe_agent

# for mp3 to pdf
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
# for webscraping
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from transformers import GPT2LMHeadModel, GPT2Tokenizer

# for EDA
import re
import pandas as pd
from openai import AzureOpenAI
from langchain_community.chat_models import AzureChatOpenAI
from langchain.agents import AgentType
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain.schema.output_parser import OutputParserException
from transformers import GPT2LMHeadModel, GPT2Tokenizer

# # for default Azure account use only
# openapi_key = "OPENAI-API-KEY"
# KVUri = f"https://eavault.vault.azure.net/"
# credential = DefaultAzureCredential()
# client = SecretClient(vault_url=KVUri, credential=credential)
# retrieved_secret = client.get_secret(openapi_key)
# main_key = retrieved_secret.value

# for local use only
load_dotenv()
main_key = os.environ["Main_key"]

os.environ["OPENAI_API_TYPE"] = "azure"
os.environ["OPENAI_API_BASE"] = "https://ea-openai.openai.azure.com/"
os.environ["OPENAI_API_KEY"] = main_key
os.environ["OPENAI_API_VERSION"] = "2023-05-15"

client = AzureOpenAI(
    api_key=main_key,
    api_version="2023-05-15",
    azure_endpoint="https://ea-openai.openai.azure.com/"
)

llm = AzureChatOpenAI(azure_deployment="gpt-35-turbo", model_name="gpt-4", temperature=0.50)
embeddings = AzureOpenAIEmbeddings(azure_deployment='text-embedding')

chunk_size = 8000
chunk_overlap = 400
custom_prompt = ''
chain_type = 'map_reduce'
num_summaries = 1

# Define global variables for download progress
current_status = ""
current_file = ""
total_files = 0
files_downloaded = 0
progress_percentage = 0

blob_list_length = 0
tot_file = 0
tot_succ = 0
tot_fail = 0
final_chunks = []
summary_chunk = []
Limit_By_Size = 0
Source_URL = ""
bar_chart_url = {}
senti_text_Q_A = ""
# word cloud
text_word_cloud = ''
nltk.download('vader_lexicon')
nltk.download('stopwords')
nltk.download('punkt')

# Your Azure Storage Account details
account_name = os.environ['account_name']
account_key = os.environ['account_key']
container_name = os.environ['container_name']

# Create a BlobServiceClient object
connection_string = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={account_key};EndpointSuffix=core.windows.net"
blob_service_client = BlobServiceClient.from_connection_string(connection_string)
container_client = blob_service_client.get_container_client(container_name)


# # for Azure use only
# account_name = "testcongnilink"
# container_name = "congnilink-container"
#
# account_url = "https://testcongnilink.blob.core.windows.net"
# default_credential = DefaultAzureCredential()
#
# blob_service_client = BlobServiceClient(account_url, credential=default_credential)
# container_client = blob_service_client.get_container_client(container_name)


def create_or_pass_folder(container_client, session):
    container_name = "congnilink-container"

    if 'login_pin' in session:
        user_folder = str(session['login_pin'])
        try:
            container_client.get_blob_client(container_name, user_folder).upload_blob("")
            print('successfully created')
            return f"Folder '{user_folder}' successfully created."
        except Exception as e:
            if "BlobNotFound" in str(e):
                try:
                    container_client.get_blob_client(container_name, user_folder).create_container()
                    return f"Folder '{user_folder}' successfully created."
                except Exception as e:
                    return f"Error creating folder '{user_folder}': {str(e)}"
            else:
                return f"Error creating folder '{user_folder}': {str(e)}"
    else:
        return "Error: 'login_pin' not found in session."


def upload_to_blob(file_content, session, blob_service_client, container_name):
    """Uploads a file to Azure Blob Storage with enhanced security and error handling.

    Args:
        file_content (http.MultipartFile): The file object to upload.
        session (dict): User session dictionary.
        blob_service_client (BlobServiceClient): Azure Blob Service client instance.
        container_name (str): Name of the Azure Blob Storage container.

    Returns:
        str: URL of the uploaded blob or an error message.
    """
    global blob_client

    if 'login_pin' not in session:
        return "Error: 'login_pin' not found in session."
    try:
        folder_name = str(session['login_pin'])

        blob_name = f"{folder_name}/{file_content.filename}"
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

        # Read the content of file_content
        content = file_content.read()

        # # Upload the content to Azure Blob Storage, overwriting the existing blob if it exists
        # blob_client.upload_blob(content, blob_type="BlockBlob",
        #                         content_settings=ContentSettings(content_type="application/octet-stream"),
        #                         overwrite=True)
        # Upload with overwrite and proper content type handling
        blob_client.upload_blob(content, blob_type="BlockBlob",
                                content_settings=ContentSettings(content_type=file_content.content_type),
                                overwrite=True)
    except Exception as e:
        print('upload_to_blob----->', str(e))

    # Return the URL of the uploaded Blob
    return blob_client.url


# def create_pdf(data):
#     folder_name = str(session['login_pin'])
#     file_name_without_extension = data.key.split('.')[0]
#     temp_pdf_path = os.path.join(folder_name, f"{file_name_without_extension}.pdf")
#     doc = SimpleDocTemplate("output.pdf", pagesize=letter)
#     styles = getSampleStyleSheet()
#     flowables = []
#
#     for name, text in data.items():
#         ptext = "<font size=12><b>{}<br/><br/></b></font>{}".format(name, text)
#         paragraph = Paragraph(ptext, style=styles["Normal"])
#         flowables.append(paragraph)
#         flowables.append(Paragraph("<br/><br/><br/>", style=styles["Normal"]))
#
#     doc.build(flowables)
# Upload the PDF file to blob storage
# upload_to_blob(temp_pdf_path, session, blob_service_client, container_name)
#
# # Temporary PDF file ko delete karna
# os.remove(temp_pdf_path)


def update_bar_chart_from_blob(session, blob_service_client, container_name):
    bar_chart = {}
    blob_list = []
    # Get the folder name from the session
    folder_name = str(session['login_pin'])
    try:
        # Get a list of blobs in the specified folder
        blob_list = blob_service_client.get_container_client(container_name).list_blobs(name_starts_with=folder_name)
        # print("blob_list------?", blob_list)

        # Iterate through each blob in the folder
        for blob in blob_list:
            file_name = blob.name.split('/')[-1]  # Extract file name from blob path

            # Update the bar_chart dictionary based on file type
            if file_name.endswith('.pdf') or file_name.endswith('.PDF'):
                file_type = 'PDF'
            elif file_name.endswith('.docx') or file_name.endswith('.doc'):
                file_type = 'DOCX'
            elif file_name.endswith('.mp3'):
                file_type = 'MP3'
            elif file_name.endswith('.xlsx') or file_name.endswith('.xls'):
                file_type = 'XLSX'
            else:
                file_type = 'Other'

            # Update bar_chart dictionary
            if file_type in bar_chart:
                bar_chart[file_type] += 1
            else:
                bar_chart[file_type] = 1
        session['bar_chart_ss'].update(bar_chart)
    except Exception as e:
        print('blob_list error------>', str(e))

    # Return the updated bar_chart dictionary
    return blob_list


def update_when_file_delete():
    global blob_list_length, Source_URL, loader, tot_file, bar_chart_url, txt_to_pdf
    txt_to_pdf = {}
    bar_chart_url = {}
    blob_list_length = 0
    tot_succ = 0
    tot_fail = 0
    final_chunks = []
    summary_chunk = []
    folder_name_azure = str(session['login_pin'])
    folder_name = os.path.join('static', 'login', folder_name_azure)
    blob_list = blob_service_client.get_container_client(container_name).list_blobs(name_starts_with=folder_name_azure)
    blob_list_length = len(list(blob_list))
    if blob_list_length == 0 and Source_URL == "":
        session['bar_chart_ss'] = {}
        session['over_all_readiness'] = 0
        session['total_success_rate'] = 0
        session['total_files_list'] = 0
        session['successful_list'] = 0
        session['failed_list'] = 0
        session['progress_list'] = 0
        print("No data Load in storage")
        return
    session['total_files_list'] = blob_list_length
    blob_list_for = blob_service_client.get_container_client(container_name).list_blobs(
        name_starts_with=folder_name_azure)

    try:
        if blob_list_length != 0:
            for blob in blob_list_for:
                blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob.name)
                file_name = blob.name.split('/')[-1]  # Extract file name from blob path
                print("blob_name_file_name---------->", file_name)
                if file_name.endswith('.pdf') or file_name.endswith('.PDF') or file_name.endswith('.mp3'):
                    temp_path = blob_client.url
                elif file_name.endswith('.xls') or file_name.endswith('.xlsx') or file_name.endswith(
                        '.docx') or file_name.endswith('.doc'):
                    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                        temp_path = temp_file.name
                        blob_data = blob_client.download_blob()
                        blob_data.readinto(temp_file)

                    # loader = AzureBlobStorageFileLoader(
                    #     conn_str=connection_string,
                    #     container=container_name,
                    #     blob_name=blob.name,
                    # )
                if '.pdf' in file_name or '.PDF' in file_name:
                    loader = PyPDFLoader(temp_path)
                elif '.mp3' in file_name:
                    loader = AssemblyAIAudioTranscriptLoader(temp_path, api_key="5bbe5761b36b4ff885dbd18836c3c723")
                elif '.docx' in file_name or '.doc' in file_name:
                    loader = Docx2txtLoader(temp_path)
                elif '.xlsx' in file_name or '.xls' in file_name:
                    loader = UnstructuredExcelLoader(temp_path)
                s_url = 'https://testcongnilink.blob.core.windows.net/congnilink-container/' + blob.name
                chunks = loader.load_and_split()
                for ele in chunks:
                    ele.metadata['source'] = s_url
                print(f"Number of chunks :: {len(chunks)}")
                if len(chunks) == 0:
                    tot_fail += 1
                    jsonify({"message": f"No Text Available in {file_name} In This File."})
                final_chunks.extend(chunks)
                summary_chunk.append({file_name: [chunks]})

                if '.mp3' in file_name and len(chunks) != 0:
                    for i, chunk in enumerate(chunks):
                        txt_to_pdf[f"{file_name}_{i + 1}"] = chunk.page_content
                    # Split file_name at the dot and append ".pdf" to the first part
                    file_name_without_extension = file_name.split('.')[0]
                    temp_pdf_path = os.path.join(folder_name, f"{file_name_without_extension}.pdf")

                    doc = SimpleDocTemplate(temp_pdf_path, pagesize=letter)
                    styles = getSampleStyleSheet()
                    flowables = []

                    for name, text in txt_to_pdf.items():
                        ptext = "<font size=12><b>{}<br/><br/></b></font>{}".format(name, text)
                        paragraph = Paragraph(ptext, style=styles["Normal"])
                        flowables.append(paragraph)
                        flowables.append(Paragraph("<br/><br/><br/>", style=styles["Normal"]))

                    doc.build(flowables)
                    # Get the filename from the path
                    file_name = os.path.basename(temp_pdf_path)
                    with open(temp_pdf_path, "rb") as file:
                        content = file.read()
                    blob_name = f"{folder_name_azure}/{file_name}"
                    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

                    # Upload the content to Azure Blob Storage, overwriting the existing blob if it exists
                    blob_client.upload_blob(content, blob_type="BlockBlob",
                                            content_settings=ContentSettings(content_type="application/pdf"),
                                            overwrite=True)

                    # Temporary PDF file ko delete karna
                    os.remove(temp_pdf_path)

                tot_succ += 1
                # Calculate progress_list
                session['successful_list'] = min(tot_succ - tot_fail, session['total_files_list'])
                session['failed_list'] = min(tot_fail, session['total_files_list'] - session['successful_list'])
                session['progress_list'] = session['total_files_list'] - session['successful_list'] - session[
                    'failed_list']
                with open(os.path.join(folder_name, 'summary_chunk.pkl'), 'wb') as f:
                    pickle.dump(summary_chunk, f)

                vectorstore = get_vectostore(final_chunks)
                vectorstore.save_local(os.path.join(folder_name, 'faiss_index'))
                session['over_all_readiness'] = session['total_files_list']
                session['total_success_rate'] = session['successful_list']
                # Check if session is modified and save it if necessary
                if session.modified:
                    # Manually save the session
                    session_interface = app.session_interface
                    session_interface.save_session(app, session, None)

                    # session_interface.save_session(app, session)
                update_bar_chart_from_blob(session, blob_service_client, container_name)
        if Source_URL != "":
            session['total_files_list'] += 1
            f_name_url = Source_URL
            file_type = 'Source_Url'
            bar_chart_url[file_type] = bar_chart_url.get(file_type, 0) + 1
            # Update bar_chart_url with values from session, if available
            if 'bar_chart_ss' in session:
                session['bar_chart_ss'].update(bar_chart_url)
            loader = WebBaseLoader(Source_URL)
            chunks_url = loader.load_and_split()
            print(f"Number of chunks :: {len(chunks_url)}")
            if len(chunks_url) == 0:
                tot_fail += 1
                return jsonify({"message": "No data available in website"})
            final_chunks.extend(chunks_url)
            summary_chunk.append({f_name_url: [chunks_url]})
            tot_succ += 1
            # Calculate progress_list
            session['successful_list'] = min(tot_succ - tot_fail, session['total_files_list'])
            session['failed_list'] = min(tot_fail, session['total_files_list'] - session['successful_list'])
            session['progress_list'] = session['total_files_list'] - session['successful_list'] - session[
                'failed_list']
            with open(os.path.join(folder_name, 'summary_chunk.pkl'), 'wb') as f:
                pickle.dump(summary_chunk, f)

            vectorstore = get_vectostore(final_chunks)
            vectorstore.save_local(os.path.join(folder_name, 'faiss_index'))
            session['over_all_readiness'] = session['total_files_list']
            session['total_success_rate'] = session['successful_list']
            update_bar_chart_from_blob(session, blob_service_client, container_name)
        print("Complete")

        return jsonify({"message": "Data loaded successfully"})
    except Exception as e:
        print("update_when_file_delete----->", str(e))
        return jsonify({'message': str(e)})


def analyze_sentiment_summ(senti_text_summ):
    """
    Analyzes the sentiment of a given text using Vader Sentiment Intensity Analyzer.

    Parameters:
        text (str): The input text for sentiment analysis.

    Returns:
        dict: A dictionary containing the percentages of positive, negative, and neutral sentiments.
    """
    # Initialize the Vader Sentiment Intensity Analyzer
    sid = SentimentIntensityAnalyzer()

    # Analyze sentiment
    sentiment_scores = sid.polarity_scores(senti_text_summ)

    # Calculate percentages
    # total = sum(abs(score) for score in sentiment_scores.values())
    # total1 = sum(sentiment_scores.values())
    total = sentiment_scores['pos'] + sentiment_scores['neg'] + sentiment_scores['neu']
    senti_Positive_summ = sentiment_scores['pos'] / total * 100
    senti_Negative_summ = sentiment_scores['neg'] / total * 100
    senti_neutral_summ = sentiment_scores['neu'] / total * 100
    return senti_Positive_summ, senti_Negative_summ, senti_neutral_summ


def perform_lda____summ(senti_text_summ, num_topics=3, n_top_words=5):
    lda_topics_summ = {}
    # Tokenization and stop words removal
    stop_words = set(stopwords.words('english'))

    def preprocess_text(text):
        tokens = word_tokenize(text.lower())
        tokens = [token for token in tokens if token not in stop_words]
        return ' '.join(tokens)

    # Preprocess conversation text
    processed_conversation = preprocess_text(senti_text_summ)

    # Create a CountVectorizer to convert text to a matrix of token counts
    vectorizer = CountVectorizer(stop_words='english')
    X = vectorizer.fit_transform([processed_conversation])

    # Fit the LDA model
    lda = LatentDirichletAllocation(n_components=num_topics, random_state=42)
    lda.fit(X)

    # Store topics and their top words in lda_topics_summ dictionary
    for topic_idx, topic in enumerate(lda.components_):
        topic_key = f"Topic{topic_idx + 1}"
        lda_topics_summ[topic_key] = [vectorizer.get_feature_names_out()[i] for i in
                                      topic.argsort()[:-n_top_words - 1:-1]]

    # Return lda_topics_summ
    return lda_topics_summ


def perform_lda___Q_A(chat_history_list, num_topics=3, n_top_words=5):
    lda_topics_Q_A = {}
    # Declare the global variable

    # Tokenization and stop words removal
    stop_words = set(stopwords.words('english'))

    def preprocess_text(text):
        tokens = word_tokenize(text.lower())
        tokens = [token for token in tokens if token not in stop_words]
        return ' '.join(tokens)

    # Preprocess conversation text
    processed_conversation = preprocess_text(chat_history_list)

    # Create a CountVectorizer to convert text to a matrix of token counts
    vectorizer = CountVectorizer(stop_words='english')
    X = vectorizer.fit_transform([processed_conversation])

    # Fit the LDA model
    lda = LatentDirichletAllocation(n_components=num_topics, random_state=42)
    lda.fit(X)

    # Store topics and their top words in lda_topics_Q_A dictionary
    for topic_idx, topic in enumerate(lda.components_):
        topic_key = f"Topic{topic_idx + 1}"
        lda_topics_Q_A[topic_key] = [vectorizer.get_feature_names_out()[i] for i in
                                     topic.argsort()[:-n_top_words - 1:-1]]

    # Return lda_topics_Q_A
    return lda_topics_Q_A


def generate_word_cloud(text_word_cloud):
    # Tokenize karein
    tokens = word_tokenize(text_word_cloud)

    # Generate WordCloud with specified width and height
    wordcloud = WordCloud(width=1200, height=800,
                          background_color='white',
                          min_font_size=10).generate(' '.join(tokens))
    folder_name = str(session['login_pin'])

    # Save the WordCloud image to a file
    wordcloud.to_file(f'static/login/{folder_name}/wordcloud.png')


def analyze_sentiment_Q_A(senti_text_Q_A):
    """
    Analyzes the sentiment of a given text using Vader Sentiment Intensity Analyzer.

    Parameters:
        text (str): The input text for sentiment analysis.

    Returns:
        dict: A dictionary containing the percentages of positive, negative, and neutral sentiments.
    """
    # Initialize the Vader Sentiment Intensity Analyzer
    sid = SentimentIntensityAnalyzer()

    # Analyze sentiment
    sentiment_scores = sid.polarity_scores(senti_text_Q_A)

    # Calculate percentages
    # total = sum(abs(score) for score in sentiment_scores.values())
    total = sentiment_scores['pos'] + sentiment_scores['neg'] + sentiment_scores['neu']
    senti_Positive_Q_A = sentiment_scores['pos'] / total * 100
    senti_Negative_Q_A = sentiment_scores['neg'] / total * 100
    senti_neutral_Q_A = sentiment_scores['neu'] / total * 100
    return senti_Positive_Q_A, senti_Negative_Q_A, senti_neutral_Q_A


def get_vectostore(text_chunks):
    vectorstore = FAISS.from_documents(text_chunks, embedding=embeddings)
    return vectorstore


def get_conversation_chain(vectorstore):
    llm = AzureChatOpenAI(azure_deployment="gpt-35-turbo")

    template = """Use the following pieces of context to answer the question at the end. If you don't know the answer, 
    just say that you don't know, don't try to make up an answer. Use three sentences maximum. Keep the answer as concise as possible. 
    {context}
    Question: {question}
    Helpful Answer:"""
    CUSTOM_QUESTION_PROMPT = PromptTemplate(input_variables=["context", "question"], template=template)
    memory = ConversationBufferMemory(memory_key="chat_history", input_key='question', return_messages=True,
                                      output_key="answer")
    conversation_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(),
        memory=memory,
        return_source_documents=True
    )
    return conversation_chain


# Start Summarization section --------

def custom_summary(docs, llm, custom_prompt, chain_type):
    custom_prompt = custom_prompt + """:\n {text}"""
    COMBINE_PROMPT = PromptTemplate(template=custom_prompt, input_variables=["text"])
    MAP_PROMPT = PromptTemplate(template="Summarize:\n{text}", input_variables=["text"])
    if chain_type == "map_reduce":
        chain = load_summarize_chain(llm, chain_type=chain_type,
                                     map_prompt=MAP_PROMPT,
                                     combine_prompt=COMBINE_PROMPT)
    else:
        chain = load_summarize_chain(llm, chain_type=chain_type)

    summaries = chain({"input_documents": docs}, return_only_outputs=True)["output_text"]
    # summaries = []
    # for i in range(num_summaries):
    #     summary_output = chain({"input_documents": docs}, return_only_outputs=True)["output_text"]
    #     summaries.append(summary_output)
    # print(summaries)
    return summaries


# def summarize_pdf(pdf_folder, user_prompt):
#     summarices = []
#     file_names = []
#     custom_prompt = user_prompt
#     for file_obj in pdf_folder:
#         file_names.append(file_obj.name)
#         doc = get_chunks(file_obj)
#         summary = custom_summary(doc, llm, custom_prompt, chain_type)
#         summarices.append(summary)
#
#     return summarices, file_names


# ## End Summarization section --------


app = Flask(__name__, template_folder="Templates")
app.debug = True
app.static_folder = "static"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///Dashboard.db"
app.config['DEBUG'] = True
db = SQLAlchemy(app)
app.secret_key = os.urandom(24)


class FileStorage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_data = db.Column(db.LargeBinary)
    file_description = db.Column(db.Text)
    created_date = db.Column(db.DateTime, default=db.func.current_timestamp())


# Define UserRoles table
class UserRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    role_id = db.Column(db.String(10), unique=True, nullable=False)
    user_details = db.relationship('UserDetails', backref='user_role', lazy=True)


# Define UserDetails table
class UserDetails(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.String(10), db.ForeignKey('user_role.role_id'), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email_id = db.Column(db.String(100), unique=True, nullable=False)
    created_date = db.Column(db.DateTime, default=db.func.current_timestamp())
    modified_date = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    status = db.Column(db.String(20), nullable=False)
    login_pin = db.Column(db.String(20), nullable=False)


def create_bar_chart():
    # update_bar_chart_from_blob(session, blob_service_client, container_name)
    bar_chart = session['bar_chart_ss']
    # print(bar_chart)
    # Check if 'bar_chart_ss' exists in session
    if bar_chart:
        x1 = list(bar_chart.values())  # Values for the bars
        y1 = list(bar_chart.keys())  # Labels for the bars
    else:
        x1 = [0]  # Values for the bars
        y1 = ["PDF"]  # Labels for the bars

    file_bar = {'x': x1, 'y': y1}

    bar_json_graph = pio.to_json(file_bar)
    return bar_json_graph


def create_pie_chart():
    title = ''
    if session['total_files_list'] != 0:
        # print('pie chart value inside fuction:', session['total_files_list'], session['successful_list'],
        #       session['failed_list'], session['progress_list'])

        total_files_list = session['total_files_list']
        successful_list = session['successful_list']
        progress_list = session['progress_list']
        failed_list = session['failed_list']
    else:
        # print('Pie Default value')
        # Default values
        total_files_list = 1
        successful_list = 0
        progress_list = 0
        failed_list = 0
        title = "Data Awaited"

    # Calculate percentages
    labels = ['Read', 'In Progress', 'Failed']
    values = [successful_list, progress_list, failed_list]

    # Create text for each segment of the pie chart
    percentages = [(value / total_files_list) * 100 for value in values]
    text = [f"{label}: {value} ({percentage:.2f}%)" for label, value, percentage in zip(labels, values, percentages)]

    # Create Pie Chart
    trace = go.Pie(values=values, labels=labels, text=text, hoverinfo='text+value', hole=.4)
    layout = go.Layout(title=title)

    pie_chart = go.Figure(data=[trace], layout=layout)

    # Optional: Customize layout parameters
    pie_chart.update_layout(
        width=260,  # Set width in pixels
        height=180,  # Set height in pixels
        margin=dict(l=10, r=60, t=50, b=20),
        legend=dict(font=dict(size=10)),  # Adjust label text size in legend
        font=dict(size=10),  # Adjust default text size
        showlegend=False
    )

    pie_chart_data = pio.to_json(pie_chart)
    return pie_chart_data


def gauge_chart_auth():
    if 'total_success_rate' in session and 'over_all_readiness' in session:
        over_all_readiness = session['over_all_readiness']
        if over_all_readiness != 0:
            success_rate = (session['total_success_rate'] / over_all_readiness) * 100
        else:
            success_rate = 0
    else:
        success_rate = 0
        over_all_readiness = 0

    gauge_fig = {'x': [success_rate], 'y': [over_all_readiness]}
    # Create the gauge figure
    # gauge_fig = go.Figure(go.Indicator(
    #     mode="gauge+number",
    #     value=success_rate,
    #     domain={'x': [0, 1], 'y': [0, 1]},
    #     title={'text': "", 'font': {'size': 5}},
    #     number={'suffix': '%', 'font': {'size': 25}},  # Add percentage sign as suffix
    #     gauge={
    #         'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
    #         'bar': {'color': "darkblue"},
    #         'bgcolor': "white",
    #         'borderwidth': 2,
    #         'bordercolor': "gray",
    #         'steps': [
    #             {'range': [0, 50], 'color': 'cyan'},
    #             {'range': [50, 100], 'color': 'royalblue'}],
    #         'threshold': {
    #             'line': {'color': "red", 'width': 4},
    #             'thickness': 0.75,
    #             'value': success_rate}
    #     }))

    # Add total files below the gauge
    # gauge_fig.add_annotation(
    #     x=0.5,
    #     y=-0.3,
    #     text=f"Total Files: {over_all_readiness}",
    #
    #     showarrow=False,
    #     font=dict(
    #         color="darkblue",
    #         size=12
    #     )
    # )

    # gauge_fig.update_layout(
    #     paper_bgcolor="white",
    #     height=190,
    #     width=250,
    #     margin=dict(l=30, r=30, t=50, b=50),
    #     font={'color': "darkblue", 'family': "Arial"}
    # )
    gauge_chart_auth = pio.to_json(gauge_fig)
    return gauge_chart_auth


def gauge_chart_CogS():
    if 'total_success_rate' in session and 'over_all_readiness' in session:
        over_all_readiness = session['over_all_readiness']
        if over_all_readiness != 0:
            success_rate = (session['total_success_rate'] / over_all_readiness) * 100
        else:
            success_rate = 0
    else:
        success_rate = 0
        over_all_readiness = 0

    gauge_fig = {'x': [success_rate], 'y': [over_all_readiness]}
    #
    # # Create the gauge figure
    # gauge_fig = go.Figure(go.Indicator(
    #     mode="gauge+number",
    #     value=success_rate,
    #     domain={'x': [0, 1], 'y': [0, 1]},
    #     title={'text': "", 'font': {'size': 5}},
    #     number={'suffix': '%', 'font': {'size': 25}},  # Add percentage sign as suffix
    #     gauge={
    #         'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
    #         'bar': {'color': "darkblue"},
    #         'bgcolor': "white",
    #         'borderwidth': 2,
    #         'bordercolor': "gray",
    #         'steps': [
    #             {'range': [0, 50], 'color': 'cyan'},
    #             {'range': [50, 100], 'color': 'royalblue'}],
    #         'threshold': {
    #             'line': {'color': "red", 'width': 4},
    #             'thickness': 0.75,
    #             'value': success_rate}
    #     }))
    #
    # # Add total files below the gauge
    # gauge_fig.add_annotation(
    #     x=0.5,
    #     y=-0.3,
    #     text=f"Total Files: {over_all_readiness}",
    #     showarrow=False,
    #     font=dict(
    #         color="darkblue",
    #         size=12
    #     )
    # )
    #
    # gauge_fig.update_layout(
    #     paper_bgcolor="white",
    #     height=180,
    #     width=300,
    #     margin=dict(l=20, r=0, t=40, b=40),  # Adjust as needed
    #     font={'color': "darkblue", 'family': "Arial"}
    # )
    gauge_chart_CogS = pio.to_json(gauge_fig)
    return gauge_chart_CogS


def gauge_chart_Q_A():
    if 'total_success_rate' in session and 'over_all_readiness' in session:
        over_all_readiness = session['over_all_readiness']
        if over_all_readiness != 0:
            success_rate = (session['total_success_rate'] / over_all_readiness) * 100
        else:
            success_rate = 0
    else:
        success_rate = 0
        over_all_readiness = 0

    gauge_fig = {'x': [success_rate], 'y': [over_all_readiness]}
    # Create the gauge figure
    # gauge_fig = go.Figure(go.Indicator(
    #     mode="gauge+number",
    #     value=success_rate,
    #     domain={'x': [0, 1], 'y': [0, 1]},
    #     title={'text': "", 'font': {'size': 5}},
    #     number={'suffix': '%', 'font': {'size': 25}},  # Add percentage sign as suffix
    #     gauge={
    #         'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
    #         'bar': {'color': "darkblue"},
    #         'bgcolor': "white",
    #         'borderwidth': 2,
    #         'bordercolor': "gray",
    #         'steps': [
    #             {'range': [0, 50], 'color': 'cyan'},
    #             {'range': [50, 100], 'color': 'royalblue'}],
    #         'threshold': {
    #             'line': {'color': "red", 'width': 4},
    #             'thickness': 0.75,
    #             'value': success_rate}
    #     }))
    #
    # # Add total files below the gauge
    # gauge_fig.add_annotation(
    #     x=0.5,
    #     y=-0.3,
    #     text=f"Total Files: {over_all_readiness}",
    #     showarrow=False,
    #     font=dict(
    #         color="darkblue",
    #         size=12
    #     )
    # )
    #
    # gauge_fig.update_layout(
    #     paper_bgcolor="white",
    #     height=180,
    #     width=300,
    #     margin=dict(l=0, r=0, t=40, b=40),  # Adjust as needed
    #     font={'color': "darkblue", 'family': "Arial"}
    # )
    gauge_chart_Q_A = pio.to_json(gauge_fig)
    return gauge_chart_Q_A


def indicator():
    if 'MB' in session:
        MB = session['MB']
        # print('MBMBMB',MB)
    else:
        MB = 0.0
    indicator = go.Figure(go.Indicator(
        mode="number+delta",
        value=MB,  # Convert MB to string before concatenating
        number={'suffix': '-MB', 'font': {'size': 15, 'color': '#0D076A'}},  # Set font color for the number
        title={"text": "Size", "font": {"size": 15, "color": "#0D076A"}},  # Set text and font color for the title
        delta={'reference': 200, 'relative': True},
        domain={'x': [0.6, 1], 'y': [0, 1]}))

    # Set height, width, and margin
    indicator.update_layout(height=75, width=80, margin=dict(l=0, r=20, t=0, b=0))
    indi = pio.to_json(indicator)
    return indi


def Sentiment_Chart_Summ(senti_Positive_summ=None, senti_Negative_summ=None, senti_neutral_summ=None):
    if senti_Positive_summ is not None and senti_Negative_summ is not None and senti_neutral_summ is not None:
        x1 = [senti_Positive_summ, senti_Negative_summ, senti_neutral_summ]  # Values for the bars
        y1 = ['Positive', 'Negative', 'Neutral']  # Labels for the bars
    else:
        x1 = [0, 0, 0, 0]  # Values for the bars
        y1 = ['Positive', 'Negative', 'Neutral']  # Labels for the bars
    senti = {'x': x1, 'y': y1}
    # # Create a bar chart
    # senti = go.Figure(data=[go.Bar(
    #     x=x1,
    #     y=y1,
    #     orientation='h',  # Horizontal orientation
    #     marker_color=['blue', 'red', 'green']  # Color for each sentiment category
    # )])

    # Update chart layout
    # senti.update_layout(xaxis_title='Count %',
    #                     margin=dict(l=0, r=0, t=0, b=0),
    #                     height=180,
    #                     width=310
    #                     )

    senti_json_graph = pio.to_json(senti)
    return senti_json_graph


def Sentiment_Chart_Q_A(senti_Positive_Q_A=None, senti_Negative_Q_A=None, senti_neutral_Q_A=None):
    if senti_Positive_Q_A is not None and senti_Negative_Q_A is not None and senti_neutral_Q_A is not None:
        x1 = [senti_Positive_Q_A, senti_Negative_Q_A, senti_neutral_Q_A]  # Values for the bars
        y1 = ['Positive', 'Negative', 'Neutral']  # Labels for the bars
    else:
        x1 = [0, 0, 0, 0]  # Values for the bars
        y1 = ['Positive', 'Negative', 'Neutral']  # Labels for the bars
    senti = {'x': x1, 'y': y1}
    # Create a bar chart
    # senti = go.Figure(data=[go.Bar(
    #     x=x1,
    #     y=y1,
    #     orientation='h',  # Horizontal orientation
    #     marker_color=['blue', 'red', 'green']  # Color for each sentiment category
    # )])
    #
    # # Update chart layout
    # senti.update_layout(xaxis_title='Count %',
    #                     margin=dict(l=0, r=0, t=0, b=0),
    #                     height=180,
    #                     width=310
    #                     )

    senti_json_graph = pio.to_json(senti)
    return senti_json_graph


# Route for Sign in page
@app.route("/", methods=["GET", "POST"])
def home():
    role_names = UserRole.query.with_entities(UserRole.name.distinct()).all()

    if request.method == "POST":
        pin = request.form.get('authpin')
        group_user = request.form.get('Grp_usr')
        print(group_user, pin)

        # Map group_user to role_id (Admin=1, Guest=2, ML Engine=3)
        role_id_mapping = {
            'Admin': 1,
            'Guest': 2,
            'ML Engine': 3
        }

        role_id = role_id_mapping.get(group_user)
        user_role = UserRole.query.filter_by(role_id=role_id).first()
        user = UserDetails.query.filter_by(role_id=role_id, login_pin=pin, status='Active').first()

        if role_id is not None and user_role and user:
            logout()  # logout function ko call
            session.modified = True
            session['logged_in'] = True
            session['login_pin'] = user.login_pin
            session['bar_chart_ss'] = {}
            session['over_all_readiness'] = 0
            session['total_success_rate'] = 0
            session['MB'] = 0.0
            session['total_files_list'] = 0
            session['successful_list'] = 0
            session['failed_list'] = 0
            session['progress_list'] = 0
            session['lda_topics_summ'] = {}
            session['lda_topics_Q_A'] = {}
            session['senti_Positive_summ'] = 0
            session['senti_Negative_summ'] = 0
            session['senti_neutral_summ'] = 0
            session['senti_Positive_Q_A'] = 0
            session['senti_Negative_Q_A'] = 0
            session['senti_neutral_Q_A'] = 0
            session['chat_history_qa'] = []
            session['summary_add'] = []
            session['summary_word_cpunt'] = 0
            create_or_pass_folder(container_client, session)  # Pass container_client and session
            folder_name = os.path.join('static', 'login', str(session['login_pin']))
            if not os.path.exists(folder_name):
                os.makedirs(folder_name)
            # Create a folder named "All_PDF" if it doesn't exist
            folder_files = os.path.join('static', 'files', str(session['login_pin']))
            if not os.path.exists(folder_files):
                os.makedirs(folder_files)
            return jsonify({'redirect': url_for('data_source')})

        # Handle invalid cases
        flash('Invalid Group User or PIN Or Status Deactivate. Please try again.', 'error')
        return jsonify({'redirect': url_for('home')})

    return render_template('index.html', role_names=role_names)


# Route for logout button
@app.route('/logout')
def logout():
    global chat_history_list, bar_chart_url
    global Limit_By_Size, Source_URL, tot_file
    global current_file, total_files, files_downloaded, progress_percentage, current_status
    bar_chart_url = {}
    chat_history_list = []
    Limit_By_Size = 0
    Source_URL = ""
    tot_file = 0

    # Define global variables for download progress
    current_status = ""
    current_file = ""
    total_files = 0
    files_downloaded = 0
    progress_percentage = 0
    # Delete the file 'final_chunks.pkl'
    # Check if session login pin exists
    if 'login_pin' in session:
        # Define the folder path using session login pin
        folder_name = os.path.join('static', 'login', str(session['login_pin']))

        # Define the file paths summary_chunkurl.pkl
        pickle_file_url = os.path.join(folder_name, 'summary_chunkurl.pkl')
        faiss_path_url = os.path.join(folder_name, 'faiss_index_url')
        pickle_file_path = os.path.join(folder_name, 'summary_chunk.pkl')
        pickle_faiss_path = os.path.join(folder_name, 'final_chunks.pkl')
        faiss_path = os.path.join(folder_name, 'faiss_index')
        wordcloud_image = os.path.join(folder_name, 'wordcloud.png')

        # # Remove 'final_chunks.pkl' if it exists within the session folder
        if os.path.exists(pickle_file_path):
            os.remove(pickle_file_path)

        # # Remove 'final_chunks.pkl' if it exists within the session folder
        if os.path.exists(pickle_faiss_path):
            os.remove(pickle_faiss_path)

        # # Remove 'faiss_index' directory and its contents if it exists within the session folder
        if os.path.exists(faiss_path) and os.path.isdir(faiss_path):
            shutil.rmtree(faiss_path)

        # # Remove 'final_chunks.pkl' if it exists within the session folder
        if os.path.exists(pickle_file_url):
            os.remove(pickle_file_url)

        # # Remove 'faiss_index' directory and its contents if it exists within the session folder
        if os.path.exists(faiss_path_url) and os.path.isdir(faiss_path_url):
            shutil.rmtree(faiss_path_url)

        if os.path.exists(wordcloud_image):
            os.remove(wordcloud_image)

    session.clear()
    # # Delete uploaded blob
    # if 'blob_name' in session:
    #     blob_name = session.pop('blob_name')  # Retrieve and remove blob name from session
    #     delete_blob_from_azure(blob_name)  # Delete the corresponding blob from Azure Blob Storage

    flash('You have been successfully logged out!', 'success')
    return redirect(url_for('home'))


@app.route('/checksession')
def check_session():
    if 'login_pin' in session:
        # print("session is live!!!")
        # Session is valid
        return jsonify({'sessionValid': True}), 200
    else:
        print("session is expired!!!")
        # Session is expired or invalid
        return jsonify({'sessionValid': False}), 401


# @app.route('/')
# def home():
#     return render_template('index.html')

@app.route('/data_source', methods=['GET', 'POST'])
def data_source():
    return render_template('DataSource.html')


@app.route('/graph_update')
def graph_update():
    bar_chart_json = create_bar_chart()
    pie_chart_json = create_pie_chart()
    gauge_auth = gauge_chart_auth()
    gauge_CogS = gauge_chart_CogS()
    gauge_Q_A = gauge_chart_Q_A()
    indi = indicator()
    try:
        senti_summ = Sentiment_Chart_Summ(session['senti_Positive_summ'], session['senti_Negative_summ'],
                                          session['senti_neutral_summ'])
    except:
        senti_summ = Sentiment_Chart_Summ()
    try:
        senti_Q_A = Sentiment_Chart_Q_A(session['senti_Positive_Q_A'], session['senti_Negative_Q_A'],
                                        session['senti_neutral_Q_A'])
    except:
        senti_Q_A = Sentiment_Chart_Q_A()
    # Return a JSON object containing all the updated data
    return jsonify({
        'bars': bar_chart_json,
        'pie_chart': pie_chart_json,
        'gauge_auth': gauge_auth,
        'gauge_CogS': gauge_CogS,
        'gauge_Q_A': gauge_Q_A,
        'indicator': indi,
        'senti_summ': senti_summ,
        'senti_Q_A': senti_Q_A
    })


@app.route('/send_data', methods=['POST'])
def send_data():
    Data = request.json
    min_date = Data.get('minDate')
    max_date = Data.get('maxDate')

    # Process the received data as needed
    # print(f"Received data: Min Date: {min_date}, Max Date: {max_date}")

    # You can perform additional processing here, such as saving to a database

    return jsonify({"status": "success"})


@app.route("/update_value", methods=["POST"])
def update_value():
    global Limit_By_Size
    if request.is_json:
        Limit_By_Size = request.json["value"]
        # print('Limit By Size(K/Count)', Limit_By_Size)
        # Do something with the value (e.g., store in database, update graph)
        return jsonify({"message": "Value updated successfully"})
    else:
        return jsonify({"error": "Unsupported Media Type"}), 415


@app.route('/popup_form', methods=['POST'])
def popup_form():
    global mb_pop, file_size_bytes
    global Limit_By_Size, Source_URL
    if request.method == 'POST':
        if 'myFile' in request.files:
            # if 'myFile' in request.files or 'audio_file' in request.files:
            #     print('Not Any File Fond')
            #     return jsonify({'message': 'File not Fond'}), 400
            mb_pop = 0  # Initialize mb_pop before the loop
            files = request.files.getlist('myFile')
            if not len(files):
                return jsonify({'message': 'File not Fond'}), 400
            print('name of file is', files)
            for file in files:
                file.seek(0, os.SEEK_END)  # Move the cursor to the end of the file
                file_size_bytes = file.tell()  # Get the current cursor position, which is the file size in bytes
                file.seek(0)  # Reset the cursor back to the beginning of the file
                mb_pop += file_size_bytes / (1024 * 1024)

            mb_p = int(mb_pop)  # Move this line here
            Limit_By_Size = int(Limit_By_Size)

            # print('Limit By Size(K/Count) file size exceeds', Limit_By_Size, mb_p)
            if mb_p >= Limit_By_Size != 0:
                print('Limit By Size(K/Count) file size exceeds')
                return jsonify({'message': 'Limit By Size(K/Count) file size exceeds'}), 400
                # Convert bytes to megabytes
            session['MB'] += float("{:.2f}".format(mb_pop))
            # Calculate total number of files
            for file in files:
                upload_to_blob(file, session, blob_service_client, container_name)

        elif request.form.get('dbURL', ''):
            db_url = request.form.get('dbURL', '')
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            print('database url n all.......', db_url, username, password)
        else:
            if not request.form.get('Source_URL', ''):
                print('No Source_URL Fond')
                return jsonify({'message': 'No Source_URL Fond'}), 400
            Source_URL = request.form.get('Source_URL', '')
            print("Source_URL Fond---->", Source_URL)
        update_bar_chart_from_blob(session, blob_service_client, container_name)

        return jsonify({'message': 'Data uploaded successfully'}), 200
    else:
        return jsonify({'message': 'Invalid request method'}), 405


@app.route('/Cogni_button', methods=['GET'])
def Cogni_button():
    global blob_list_length, Source_URL
    try:
        start_time = time.time()
        print('Cogni_button Press')
        response = update_when_file_delete()
        if blob_list_length == 0 and Source_URL == "":
            session['bar_chart_ss'] = {}
            session['over_all_readiness'] = 0
            session['total_success_rate'] = 0
            session['total_files_list'] = 0
            session['successful_list'] = 0
            session['failed_list'] = 0
            session['progress_list'] = 0
            print("No data Load in storage cogni button code")
            return jsonify({'message': 'No data Load in storage'})
        # Set Timer
        end_time = time.time()  # Get the current time when the function ends
        elapsed_time = end_time - start_time  # Calculate the elapsed time

        print(f"Function took--------->  {elapsed_time} <--------- seconds to execute.")
        return response
    except Exception as e:
        print("Cogni_button_error_message----->", str(e))
        return jsonify({'message': str(e)}), 500


@app.route("/Summary", methods=['GET', 'POST'])
def summary():
    session['summary_word_cpunt'] = 0
    return render_template('summary.html')


@app.route("/summary_input", methods=['POST'])
def summary_input():
    global text_word_cloud
    session['summary_add'] = []
    try:
        # start_time = time.time()
        # Load the session login pin
        folder_name = os.path.join('static', 'login', str(session['login_pin']))

        # Load the pickle file from the folder
        pickle_file_path = os.path.join(folder_name, 'summary_chunk.pkl')
        with open(pickle_file_path, 'rb') as f:
            all_summary = pickle.load(f)
        print(f"myEntry ::: {len(all_summary)}")
        # print(myEntry)
        custom_p = request.get_json('summary_que').get('summary_que')
        # print(custom_p)
        if session['summary_word_cpunt'] == 0:
            return jsonify({'message': 'summary word count is zero'})
        else:
            custom_p = custom_p + ' and summary in ' + str(session['summary_word_cpunt']) + ' word'
        summ = []
        counter = 1

        # Flatten the nested structure of myEntry
        flattened_entries = [(filename, document) for entry in all_summary for filename, documents_list in entry.items()
                             for
                             document in documents_list]

        for filename, document in flattened_entries:
            summary = custom_summary(document, llm, custom_p, chain_type)
            key = f'{filename}--{counter}--'
            summary_dict = {'key': key, 'value': summary}
            summ.append(summary_dict)
            counter += 1

        # print("Summaries:", summ)

        # Set Timer
        # end_time = time.time()  # Get the current time when the function ends
        # elapsed_time = end_time - start_time  # Calculate the elapsed time

        # print(f"Function took {elapsed_time} seconds to execute.")
        senti_text_summ = ' '.join(entry['value'] for entry in summ)
        session['senti_Positive_summ'], session['senti_Negative_summ'], session[
            'senti_neutral_summ'] = analyze_sentiment_summ(senti_text_summ)
        # senti_Positive_summ = 0
        # senti_Negative_summ = 0
        # senti_neutral_summ = 0
        generate_word_cloud(senti_text_summ)
        session['lda_topics_summ'] = perform_lda____summ(senti_text_summ)
        session['summary_add'].extend(summ)

        return jsonify(session['summary_add'][::-1])
    except Exception as e:
        print('Exception of summary_input:', str(e))
        return jsonify({'message': 'No data Load'})


@app.route("/Cogservice_Value_Updated", methods=["POST"])
def Cogservice_Value_Updated():
    if request.is_json:
        summary_word_cpunt = request.json["value"]
        session['summary_word_cpunt'] = summary_word_cpunt
        print(session['summary_word_cpunt'])
        # Do something with the value (e.g., store in database, update graph)
        return jsonify({"message": "CogniLink Value updated successfully"})
    else:
        return jsonify({"error": "Unsupported Media Type"}), 415


@app.route('/CogniLink_Services_QA', methods=['GET', 'POST'])
def ask():
    return render_template('ask.html')


@app.route('/ask', methods=['POST'])
def ask_question():
    global senti_text_Q_A
    # chat_history_list = []
    try:
        data = request.get_json()
        question = data['question']

        folder_name = os.path.join('static', 'login', str(session['login_pin']))
        faiss_index_path = os.path.join(folder_name, 'faiss_index')

        new_db = FAISS.load_local(faiss_index_path, embeddings, allow_dangerous_deserialization=True)
        conversation = get_conversation_chain(new_db)
        response = conversation({"question": question})

        doc_source = [response["source_documents"][0].metadata["source"]]
        doc_page_num = [response["source_documents"][0].metadata.get("page", 0) + 1]

        final_chat_hist = [(response['chat_history'][i].content if response['chat_history'][i] else "",
                            response['chat_history'][i + 1].content if response['chat_history'][i + 1] else "",
                            doc_source[i], doc_page_num[i])
                           for i in range(0, len(response['chat_history']), 2)]

        chat_history_list = [{"question": chat_pair[0],
                              "answer": chat_pair[1],
                              "source": chat_pair[2],
                              "page_number": chat_pair[3]}
                             for chat_pair in final_chat_hist]

        senti_text_Q_A = ' '.join(entry['answer'] for entry in chat_history_list)
        session['senti_Positive_Q_A'], session['senti_Negative_Q_A'], session[
            'senti_neutral_Q_A'] = analyze_sentiment_Q_A(senti_text_Q_A)
        session['lda_topics_Q_A'] = perform_lda___Q_A(senti_text_Q_A)
        session['chat_history_qa'].extend(chat_history_list)

        return jsonify({'chat_history': session['chat_history_qa'][::-1]})
    except Exception as e:
        print("Exception of ask_question:", str(e))
        return jsonify({'message': 'No data Load'})


@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    try:

        # sentiment variable for Q_A
        session['lda_topics_Q_A'] = {}
        session['senti_Positive_Q_A'] = 0
        session['senti_Negative_Q_A'] = 0
        session['senti_neutral_Q_A'] = 0
        session['chat_history_qa'] = []
        # print('Cleared Chat')
        return jsonify({'message': 'Chat history cleared successfully'})
    except Exception as e:
        print('error in Cleared Chat', str(e))
        return jsonify({'message': str(e)})


@app.route('/clear_chat_summ', methods=['POST'])
def clear_chat_summ():
    global text_word_cloud
    try:
        # Check if session login pin exists
        if 'login_pin' in session:
            # Define the folder path using session login pin
            folder_name = os.path.join('static', 'login', str(session['login_pin']))
            # Define the file paths
            # pickle_file_path = os.path.join(folder_name, 'summary_chunk.pkl')
            wordcloud_image = os.path.join(folder_name, 'wordcloud.png')
            if os.path.exists(wordcloud_image):
                os.remove(wordcloud_image)
            # Remove 'final_chunks.pkl' if it exists within the session folder
            # if os.path.exists(pickle_file_path):
            #     os.remove(pickle_file_path)
        # if os.path.exists('static/images/wordcloud.png'):
        #     os.remove('static/images/wordcloud.png')
        text_word_cloud = ''
        session['summary_word_cpunt'] = 0
        session['lda_topics_summ'] = {}
        session['senti_Positive_summ'] = 0
        session['senti_Negative_summ'] = 0
        session['senti_neutral_summ'] = 0
        session['summary_add'] = []
        # sentiment variable for summary
        # print('Cleared Chat')
        return jsonify({'message': 'Summary cleared successfully'})
    except Exception as e:
        print('error in Cleared Chat', str(e))
        return jsonify({'message': str(e)})


@app.route('/lda_data', methods=['GET'])
def get_lda_data():
    lda_type = request.args.get('type')  # Get the type parameter (either 'Q_A' or 'summ')

    if lda_type == 'Q_A':
        return jsonify(session['lda_topics_Q_A'])
    elif lda_type == 'summ':
        return jsonify(session['lda_topics_summ'])
    else:
        return jsonify({'error': 'Invalid type parameter'})


@app.route("/delete/<file_name>", methods=["DELETE"])
def delete(file_name):
    try:
        folder_name = session.get('login_pin')  # Make sure 'login_pin' is set in the session
        blobs = container_client.list_blobs(name_starts_with=folder_name)

        # Find the blob with the matching file name
        target_blob = next((blob for blob in blobs if blob.name.split('/')[-1] == file_name), None)
        if target_blob:
            blob_client = container_client.get_blob_client(target_blob.name)
            blob_client.delete_blob()
            update_when_file_delete()
            update_bar_chart_from_blob(session, blob_service_client, container_name)
            return jsonify({'message': f'File {file_name} deleted successfully'})
        else:
            return jsonify({'error': f'File {file_name} not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/table_update", methods=['GET'])
def get_data_source():
    folder_name = session.get('login_pin')  # Make sure 'login_pin' is set in the session
    blobs = container_client.list_blobs(name_starts_with=folder_name)

    # Construct the URLs for each blob based on your Azure Blob Storage configuration
    data = [{'name': blob.name.split('/')[1],
             'url': f"https://{blob_service_client.account_name}.blob.core.windows.net/{container_name}/{blob.name}"}
            for blob in blobs]
    return jsonify(data)


@app.route("/webcrawler", methods=['GET', 'POST'])
def webcrawler():
    global current_file, total_files, files_downloaded, progress_percentage, current_status

    folder_name = os.path.join('static', 'files', str(session['login_pin']))
    try:
        url_get = request.get_json()
        url = url_get['url']
        # Now you have the URL received from the form
        print("Received URL:", url)
        current_status = "Website URL Received"

        # url = "https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx"
        response = requests.get(url)

        # Extract PDF info from the table rows
        pdf_info_list = extract_pdf_info_from_table(response.content)

        # Update global variables for download progress
        total_files = len(pdf_info_list)
        files_downloaded = 0
        progress_percentage = 0
        current_status = "Crawling in progress..."
        for pdf_name, pdf_link in pdf_info_list:
            try:
                pdf_url = pdf_link
                # Replace invalid characters in filename
                name = pdf_name.replace('/', '-')  # Replace '/' with '-'
                if not name:
                    name = os.path.basename(urlparse(pdf_url).path)  # Use the last part of the URL as filename
                download_pdf(pdf_url, folder_name, name)
                # Increment files downloaded count
                files_downloaded += 1
                # Update progress percentage
                progress_percentage = int(files_downloaded / total_files * 100)
            except Exception as e:
                print(f"Error occurred: {e}")
        # Define global variables for download progress
        current_status = "File downloaded successfully"
        return jsonify({'message': 'All files downloaded successfully'})
    except Exception as e:
        print("Exception of web crawling:", str(e))
        return jsonify({'message': 'URL Not found'})


def extract_pdf_info_from_table(html_content):
    # Parse the HTML content
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all table rows
    rows = soup.find_all('tr')

    pdf_info_list = []

    # Iterate over each row
    for row in rows:
        # Extract data from each row
        cells = row.find_all('td')
        if len(cells) >= 2:
            pdf_name = cells[0].text.strip()
            pdf_link = cells[1].find('a')['href']
            pdf_info_list.append((pdf_name, pdf_link))

    return pdf_info_list


def download_pdf(url, folder_name, filename):
    global current_file

    response = requests.get(url)
    file_path = os.path.join(folder_name, filename + '.pdf')

    print(f"Downloading: {filename} from {url} to {file_path}")
    current_file = filename  # Update current file being downloaded

    with open(file_path, 'wb') as f:
        f.write(response.content)

    print(f"Downloaded: {filename}")


@app.route("/download_progress", methods=['GET'])
def download_progress():
    global current_file, total_files, files_downloaded, progress_percentage, current_status

    # current_file = "Master Direction – Acquisition or Transfer of Immovable Property under Foreign Exchange
    # Management Act, 1999 (Updated as on September 01, 2022)" total_files = 10 files_downloaded = 5
    # progress_percentage = int(files_downloaded / total_files * 100)

    # Return JSON response with progress information
    return jsonify({
        'current_status': current_status,
        'total_files': total_files,
        'files_downloaded': files_downloaded,
        'progress_percentage': progress_percentage,
        'current_file': current_file
    })


@app.route("/fetch_pdf_files", methods=['GET', 'POST'])
def fetch_pdf_files():
    # Directory path where PDF files are located
    directory_path = "static/files/" + session.get('login_pin', '')

    # Get list of PDF files in the directory
    pdf_files = [file for file in os.listdir(directory_path) if file.endswith(".pdf")]

    # Return the list of PDF files to the client
    return jsonify({"pdf_files": pdf_files})


# This function should contain your file deletion logic
def delete_file(directory_path, file_name):
    try:
        file_path = os.path.join(directory_path, file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        else:
            print("File does not exist:", file_path)
            return False
    except Exception as e:
        print("Error occurred while deleting file:", str(e))
        return False


@app.route("/select_pdf_file", methods=['POST'])
def select_pdf_file():
    try:
        folder_name_azure = str(session['login_pin'])
        data = request.get_json()
        file_name = data.get('fileName')
        login_pin = session.get('login_pin')

        # print("file name----->", file_name)

        if login_pin is None:
            return jsonify({'message': 'User session not found'}), 400

        if data.get('deletePopup') == 'deletepopupn3':
            directory_path = "static/files/" + login_pin
            res = delete_file(directory_path, file_name)
            # Delete the file
            if res is True:
                print("file deleted")
                return jsonify({'message': 'Successfully File Deleted'}), 200
            else:
                return jsonify({'message': 'Failed To Delete'}), 500
        else:
            # Assuming you have the folder name for Azure stored in `folder_name_azure`
            blob_name = f"{folder_name_azure}/{file_name}"
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

            file_path = os.path.join("static/files", login_pin, file_name)
            with open(file_path, "rb") as file:
                file_content = file.read()

            # Upload the content to Azure Blob Storage, overwriting the existing blob if it exists
            blob_client.upload_blob(file_content, blob_type="BlockBlob",
                                    content_settings=ContentSettings(content_type="application/pdf"),
                                    overwrite=True)
            directory_path = "static/files/" + login_pin

            res = delete_file(directory_path, file_name)

        # Delete the file
        if res is True:
            print("file deleted")
            return jsonify({'message': 'Successfully File Loaded In Cognilink Application'}), 200
        else:
            return jsonify({'message': 'Failed To Loaded In Cognilink Application'}), 500
    except Exception as e:
        return jsonify({'message': 'Error occurred while deleting file: {}'.format(str(e))}), 500


Q_data = {}


@app.route("/Eda_Process", methods=['POST'])
def Eda_Process():
    output = ''
    fig_json = {}
    question = request.json['question']
    print("Question received:", question)
    # file_url = request.json['fileUrl']
    # print(file_url)
    # modified_path = file_url.replace(" ", "")
    # print("modified_path----->", modified_path)
    # response = requests.get(modified_path)
    # # Create a temporary file to save the downloaded content
    # with tempfile.NamedTemporaryFile(delete=False) as temp_file:
    #     # Write the content of the blob to the temporary file
    #     temp_file.write(response.content)
    #     temp_file_path = temp_file.name
    # print(temp_file_path)
    # df = pd.read_excel(temp_file_path, engine='xlrd')
    df = pd.read_excel("NSE Academy - Feedback Form for Students(ES)- AY 2023-24(1-95).xlsx")
    # print(df.head(5))
    df.columns = df.columns.str.replace(' ', '_')
    df.columns.str.replace('  ', '_')
    prompt = f"""You are a python expert. You will be given questions for
        manipulating an input dataframe.
        The available columns are: `{df.columns}`.
        Use them for extracting the relevant data.
    """
    anwser = [{"role": "system", "content": prompt}, {"role": "user", "content": question}]

    # if 'plot' in anwser[-1]["content"].lower():
    if question and 'plot' in anwser[-1]["content"].lower():

        code_prompt = """
            Generate the code <code> for plotting the previous data in plotly,
            in the format requested. The solution should be given using plotly
            and only plotly. Do not use matplotlib. Do not load any data set use default loaded data as df.
            Return the code <code> in the following
            format ```python <code>```
        """
        anwser.append({
            "role": "assistant",
            "content": code_prompt
        })
        response = client.chat.completions.create(
            model="gpt-35-turbo",
            messages=anwser,
            max_tokens=256
        )

        code = extract_python_code(response.choices[0].message.content)

        # code = extract_python_code(response["choices"][0]["messages"][0]["content"])
        print("code------->", code)

        if code is None:
            warning = ("Couldn't find data to plot in the chat. Check if the number of tokens is too low for the data "
                       "at hand. I.e. if the generated code is cut off, this might be the case.")
            return jsonify({"message": warning})
        else:
            # In the Flask route /Eda_Process
            code = code.replace("fig.show()", "")

            # Dictionary to hold globals after exec
            exec_globals = {}

            # Execute the code
            exec(code, {'df': df}, exec_globals)

            # Retrieve 'fig' from the globals
            fig = exec_globals.get('fig')

            # After retrieving 'fig' from the globals
            if fig is not None and isinstance(fig, go.Figure):
                # Convert the Plotly figure to PNG image bytes
                img_bytes = pio.to_image(fig, format="png")

                # Encode the image bytes to base64
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                # Return the base64 encoded image as a Flask response
                return jsonify({"image": img_base64})
            else:
                return jsonify(
                    {"error": "Failed to generate plot: 'fig' is not defined or is not a valid Plotly figure"})
    else:

        llm = AzureChatOpenAI(azure_deployment="gpt-4-0125-preview", model_name="gpt-4", temperature=0.50,
                              max_tokens=256)
        pandas_df_agent = create_pandas_dataframe_agent(
            llm,
            df,
            verbose=True,
            return_intermediate_steps=True,
            agent_type=AgentType.OPENAI_FUNCTIONS
        )

        answ = pandas_df_agent.invoke(anwser)
        print("answ---->", answ)
        if answ["intermediate_steps"]:
            print("Intermediate")
            action = answ["intermediate_steps"][-1][0].tool_input["query"]
            output = f"Executed the code ```{action}```"
            output = answ["output"] + output
        else:
            output = answ["output"]

        # Generate dummy graph data
        graph_data = fig_json

        # Combine text and graph data into a single response
        response = {
            'success': True,
            'message': 'Question processed successfully',
            'text': output,
            'graph': graph_data
        }

        return jsonify(response)

    # return jsonify({'success': True, 'message': 'Data processed successfully'})
    # else:
    #     return jsonify({'success': False, 'message': 'No file URL provided'})


def extract_python_code(text):
    pattern = r'```python\s(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        return None
    else:
        return matches[0]


@app.route('/blank')
def blank():
    return render_template('blank.html')


@app.route('/EDA', methods=['GET', 'POST'])
def eda_analysis():
    return render_template('EDA.html')


@app.route('/signup')
def signup():
    return render_template('signup.html')


@app.route('/file_manager')
def file_manager():
    return render_template('webCrawl_file_manager.html')


# @app.route('/typography')
# def typography():
#     return render_template('typography.html')

# @app.route('/widget')
# def widget():
#     return render_template('widget.html')

@app.route('/_404')
def _404():
    return render_template('_404.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
