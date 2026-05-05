import json
import serpapi

client = serpapi.Client(api_key="0eec9a4a69d0a7977e33e52b555478e578f92a76bdfba3568503c9f2e008ab2e")
results = client.search({
  "engine": "google_jobs",
  "location": "United Kingdom",
  "google_domain": "google.co.uk",
  "q": ["AI Engineer", "Data Scientist", "Machine Learning Engineer", "Deep Learning Engineer", "NLP Engineer", 
        "Computer Vision Engineer", "AI Researcher", "AI Software Engineer", "AI Consultant", "AI Product Manager",
        "Data Engineer","Devops Engineer", "Cloud Engineer", "Big Data Engineer", "Data Analyst", 
        "Business Intelligence Analyst", "Data Architect", "Data Science Manager", 
        "Data Science Consultant", "Data Science Product Manager","Junior AI Engineer", "Entry-level AI Engineer", "Junior Data Scientist", "entry-level Data Scientist","AI Developer", "AI Programmer", "AI Software Developer", 
        "AI Research Scientist", "AI Research Engineer",]
})

with open ("jobs_results.json", "w") as file:
    json.dump(results["jobs_results"], file, indent=4)


with open ("jobs_results.json", "r") as file:
    data = json.load(file)
    job_descriptions = [job['description'] for job in data]
print(len(job_descriptions))
print(job_descriptions[0].replace("\\n", " "))

  