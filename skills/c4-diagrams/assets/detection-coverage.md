# What the script detects, and what it misses

`analyze_repository.py` is pattern-based. This file is the list of patterns it
knows and the gaps they leave. Read the gaps before you decide a thing is not
there: the facts are a floor, not a ceiling.

## Detected

- **Containers:** .NET `Sdk.Web`/`Worker`/Functions/`Exe` projects; Spring Boot/Quarkus/Micronaut modules with a main class or boot plugin (library modules are not containers); Go `package main` folders; Python packages using FastAPI/Flask/Django/Streamlit/Gradio/MCP/Celery or declaring `[project.scripts]` (a folder holding only a `requirements.txt` counts as a package, and so does an inferred source root in a repository that declares no packaging at all); Node.js packages using Express/Nest/Next/React/Vue/MCP or declaring `bin`; docker-compose services (a `build:` context is matched to the container below it).
- **Data stores:** EF Core providers, Spring Data templates (`RedisTemplate`, `MongoTemplate`, `KafkaTemplate`…), DB/cache/queue clients in Python, Node.js and Go, Maven/NuGet drivers, docker-compose images.
- **External systems:** SDKs (Anthropic, OpenAI, AWS, Stripe, Sentry, Microsoft Graph…), URL hosts in files that use an HTTP or SOAP client (URLs in comments are skipped), and URL settings in `appsettings*.json`, `application*.yml`/`.properties` and `config.yml`.
- **Links between containers:** compose `depends_on`, and front-end dev-server proxies (Vite, webpack, Next.js rewrites, CRA `proxy`) to the back end.
- **Components:** the modules each container is built from (projects, Maven/Gradle modules, Go packages, Python/TS folders), and inside them the code structure: Java/Kotlin packages, C# namespaces and Go packages grouped below each module's root, with import edges. Stores and external systems attach to the package that uses them. Tests and third-party code (`vendor/`, `wwwroot/lib`, `*.min.js`) are left out; dense graphs hide shortcut edges; more than 20 components are split per module or folder.
- **Report sections:** HTTP endpoints (Spring, JAX-RS, ASP.NET attribute and conventional `{controller}/{action}` routes, Express/Fastify/Koa/Nest, FastAPI/Flask/Django, Go net/http, gin, echo and chi), deployment (compose, Dockerfiles, Kubernetes, CI, hosting), environment variables with defaults, and a technology inventory per container.

## Known blind spots

Each of these is a thing the detectors cannot see. When the code shows one, add
it to `c4-model.json` yourself with `evidence` pointing at the code.

- **A call made through your own wrapper.** A URL host counts as an external
  system only when the file holding it also imports an HTTP or SOAP client. A
  module that calls `post_json(...)` from an in-house helper, and imports
  nothing else, yields no external system at all. Clients wrapped once are the
  single most common miss.
- **A URL that only lives in an environment variable.** It is reported under
  `configuration.variables` with its default, never as an external system. A
  `*_URL` or `*_ENDPOINT` variable pointing outside the system is an external
  system that nobody drew.
- **Development-only services.** A docker-compose service is a container
  whatever it is for: a database console, a mail catcher, a mock server and a
  production API all look alike. Nothing marks one dev-only. Put the dev-only
  ones in `excluded` with a reason — leaving them in the model puts a tool the
  team never deploys in front of the reader.
- **Development-only dependencies.** A package in `devDependencies` (or a test
  or lint extra) appears in the container's inventory. It is not a container
  and usually not a dependency of the running system.
- **Queue consumers, scheduled jobs, gRPC and in-house SDKs.** There is no
  pattern for "this process consumes a topic" or "this is called on a cron".
  Follow the entry points in the code.
- **Python with more than one distribution.** When a repository holds several
  `pyproject.toml`/`setup.py` distributions, the graph's nodes are the
  distributions themselves, so a container's component graph can be a single
  box. A repository with one distribution is expanded into its packages and
  modules instead. A one-box Level 3 means the graph could not go deeper, not
  that the container has one part: describe its packages from the code.
- **An inferred boundary is a guess.** Where a repository declares no
  Python packaging, the source roots are read from the layout and reported
  as `Inferred projects:`. The guard keeps tooling and test folders out, but
  nothing tells a real module boundary from a folder someone happened to
  make. Check them against the code before you build the model on them.
- **A library is not a container, and the reverse.** A package with no
  framework and no entry point is folded in as a *component* of whatever uses
  it. That is right — but do not promote it to a container because it has its
  own manifest, and do not drop a real container because its framework is not
  on the list above.

## When nothing is detected

No containers and an empty graph means the detectors did not recognise the
stack, not that the repository is empty. Build the picture from the source by
hand and say so in the report.
