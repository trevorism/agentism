# Dependency upgrade playbook

Conventions for upgrading a Micronaut/Groovy service to current dependencies.

---

## Scope

Use this checklist when the user asks for a dependency modernization or release bump.

1. Upgrade framework/plugin/dependency versions to the latest requested versions.
2. Bump the project version with a MINOR increment.
3. Update CI/runtime metadata to the matching Java level.
4. Add a changelog entry for the new version.
5. Add a workflow to build on pull requests if missing.

---

## Required version bump rules

- Always perform a minor version increment.
- Examples:
  - `0-4-0` -> `0-5-0`
  - `0.5.0` -> `0.6.0`
- Keep the existing version format already used by the project.
- Apply the same new version everywhere it is surfaced:
  - `Application.groovy`
  - `RootController.groovy` version endpoint
  - build/release metadata files

---

## Required Java and runtime updates

- In `.github/workflows/*`, set JDK version to `25`.
- Audit every relevant workflow file instead of updating only the obvious CI files.
- At minimum, check `build.yml`, `test.yml`, and `deploy.yml` when they exist.
- Also inspect any reusable workflow callers or environment-specific workflow files that pass Java/JDK/runtime values.
- In `src/main/app.yaml`, set runtime to `java25`.

---

## Required Gradle updates

### Gradle wrapper upgrade (required)

Run the wrapper task explicitly and in isolation so it does not get mixed with build/test tasks.

This is mandatory: do **not** manually edit `gradle/wrapper/gradle-wrapper.properties` to simulate a wrapper upgrade. The upgrade must come from running the wrapper task so wrapper executables/artifacts are regenerated and can be committed.

```powershell
.\gradlew.bat --stop
.\gradlew.bat wrapper --gradle-version latest --distribution-type bin --no-daemon --stacktrace
```

If `latest` is not accepted in the target repo/tooling, run the same command with a concrete version.

```powershell
.\gradlew.bat wrapper --gradle-version 9.5.1 --distribution-type bin --no-daemon --stacktrace
```

Notes:
- Use `--no-daemon` to avoid daemon startup/lock delays that can look like hangs in automation.
- Run wrapper as a standalone command, then run tests in a separate command.
- Run this after changes to build.gradle files but before any other build/test tasks
- Never "upgrade wrapper" by editing `gradle/wrapper/gradle-wrapper.properties` directly.
- Verify updates include `gradle/wrapper/gradle-wrapper.properties` (distribution URL) **and** wrapper executable/artifact files (for example `gradlew`, `gradlew.bat`, and `gradle/wrapper/gradle-wrapper.jar` when present).

### buildscript classpath

```groovy
buildscript {
    dependencies {
        classpath 'com.google.cloud.tools:appengine-gradle-plugin:2.8.7'
        classpath 'com.trevorism:gradle-acceptance-plugin:2.8.2'
    }
}
```

### plugins block

```groovy
plugins {
    id("groovy")
    id("com.gradleup.shadow") version "9.4.1"
    id("io.micronaut.application") version "5.0.0"
    id("jacoco")
}
```

### dependency examples to target

```groovy
dependencies {
    implementation 'io.projectreactor:reactor-core:3.8.5'
    implementation 'com.google.code.gson:gson:2.14.0'
    implementation 'com.trevorism:kraken:1.1.0'
    implementation 'com.trevorism:gradle-acceptance-plugin:2.8.2'
    implementation 'com.trevorism:schedule-client:1.0.0'
    implementation 'com.trevorism:http-utils:2.2.0'
    implementation 'com.trevorism:reactions-client:0.6.0'
    implementation 'com.trevorism:datastore-client:4.1.0'
    implementation 'com.trevorism:gradle-release-plugin:0.7.0'
    implementation 'com.trevorism:threshold-client:1.1.0'
    implementation 'com.trevorism:secure-utils:6.0.0'
    implementation 'com.trevorism:secure-http-utils:3.2.1'
    implementation 'com.trevorism:micronaut-security-utils:2.3.3'
    implementation 'com.trevorism:micronaut-utility-beans:1.7.2'
    implementation 'com.trevorism:micronaut-platform-proxy:0.1.1'
    implementation 'com.trevorism:event-client:0.1.1'
}
```

### additional required Gradle properties

- Bump the App Engine plugin/version where present.
- Ensure `gradle.properties` contains:

```properties
micronautVersion=5.0.0
```

---

## Release notes requirement

- Add a new entry in `changelog.md` for the new version.
- Include at minimum:
  - new version number
  - concise overview of upgrades

## Build workflow requirement

- Note: call-cypress does not need a JDK_VERSION update since it does not run Java code
- If not already present, add a GitHub Actions workflow to build the project on pull requests.
- Example workflow name: `build.yml`. Make sure it has write-all permissions and runs on pull requests to master.
- Content:

```yaml
name: Build and test on pull requests

on:
  pull_request:
  workflow_dispatch:

permissions: write-all

jobs:
  call-build:
    uses: trevorism/actions-workflows/.github/workflows/build.yml@master
    with:
      JDK_VERSION: 25
```