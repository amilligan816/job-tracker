"""Skill vocabulary used by the deterministic matcher.

Canonical name -> the spellings that mean it. Aliases are matched
case-insensitively on word boundaries, so keep them lowercase.

This is plain data: add a row and the matcher picks it up. It does not try to be
exhaustive -- it covers the terms that actually decide software job matches.
"""

SKILLS: dict[str, tuple[str, ...]] = {
    # --- languages
    "Python": ("python",),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "Java": ("java",),
    "Kotlin": ("kotlin",),
    "Go": ("golang", "go"),
    "Rust": ("rust",),
    "Ruby": ("ruby",),
    "PHP": ("php",),
    "C#": ("c#", "csharp", ".net", "dotnet"),
    "C++": ("c++", "cpp"),
    "C": ("c",),
    "Scala": ("scala",),
    "Swift": ("swift",),
    "Elixir": ("elixir",),
    "R": ("r",),
    "SQL": ("sql",),
    "Bash": ("bash", "shell scripting", "zsh"),
    # --- frontend
    "React": ("react", "react.js", "reactjs"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Angular": ("angular",),
    "Svelte": ("svelte", "sveltekit"),
    "Next.js": ("next.js", "nextjs"),
    "Redux": ("redux",),
    "Tailwind": ("tailwind", "tailwindcss"),
    "MUI": ("mui", "material-ui", "material ui"),
    "HTML": ("html", "html5"),
    "CSS": ("css", "css3", "sass", "scss"),
    "Webpack": ("webpack",),
    "Vite": ("vite",),
    # --- backend / frameworks
    "FastAPI": ("fastapi",),
    "Django": ("django",),
    "Flask": ("flask",),
    "Node.js": ("node.js", "nodejs", "node"),
    "Express": ("express", "express.js"),
    "Spring": ("spring", "spring boot"),
    "Rails": ("rails", "ruby on rails"),
    "Laravel": ("laravel",),
    "GraphQL": ("graphql",),
    "gRPC": ("grpc",),
    "REST": ("rest", "restful", "rest api", "rest apis"),
    "Microservices": ("microservices", "microservice"),
    # --- data stores
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql", "mariadb"),
    "MongoDB": ("mongodb", "mongo"),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch", "opensearch"),
    "Cassandra": ("cassandra",),
    "DynamoDB": ("dynamodb",),
    "Snowflake": ("snowflake",),
    "BigQuery": ("bigquery",),
    "SQLite": ("sqlite",),
    "S3": ("s3", "object storage", "minio"),
    # --- infra / cloud
    "AWS": ("aws", "amazon web services"),
    "GCP": ("gcp", "google cloud"),
    "Azure": ("azure",),
    "Docker": ("docker", "containers", "containerization"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform",),
    "Ansible": ("ansible",),
    "Helm": ("helm",),
    "Linux": ("linux", "unix"),
    "Nginx": ("nginx",),
    "Serverless": ("serverless", "lambda", "aws lambda"),
    # --- data / streaming
    "Kafka": ("kafka",),
    "RabbitMQ": ("rabbitmq",),
    "Airflow": ("airflow",),
    "Spark": ("spark", "pyspark"),
    "dbt": ("dbt",),
    "Pandas": ("pandas",),
    "ETL": ("etl", "elt"),
    # --- ml
    "Machine Learning": ("machine learning", "ml"),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "LLMs": ("llm", "llms", "large language models", "genai", "generative ai"),
    "NLP": ("nlp", "natural language processing"),
    # --- practice / tooling
    "CI/CD": ("ci/cd", "cicd", "continuous integration", "continuous delivery"),
    "Git": ("git", "github", "gitlab"),
    "Testing": ("unit testing", "integration testing", "test automation", "pytest", "jest"),
    "Agile": ("agile", "scrum", "kanban"),
    "Observability": ("observability", "monitoring", "prometheus", "grafana", "datadog"),
    "Security": ("security", "appsec", "oauth", "authentication", "authorization"),
    "Distributed Systems": ("distributed systems", "distributed system"),
    "System Design": ("system design", "architecture"),
    "Mentoring": ("mentoring", "mentorship", "coaching"),
    "Technical Leadership": ("technical leadership", "tech lead", "team lead"),
}

# Terms that are also ordinary English words. A bare match is not enough: these
# only count when an unambiguous alias appears, or when the match sits in a
# list-like context ("Go, Python, Rust") rather than in a sentence.
AMBIGUOUS_ALIASES = frozenset(
    {"go", "c", "r", "swift", "rust", "ml", "ts", "js", "node", "express", "spring", "security"}
)
