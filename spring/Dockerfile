# ── 빌드 ────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /src

# 의존성만 먼저 받아 캐시한다. src만 바뀌면 이 레이어는 재사용된다
COPY gradle gradle
COPY gradlew settings.gradle build.gradle ./
RUN chmod +x gradlew && ./gradlew dependencies --no-daemon --quiet || true

COPY src src
RUN ./gradlew bootJar --no-daemon --quiet -x test

# 레이어드 jar로 풀어둔다. 코드만 고쳤을 때 30MB 의존성 레이어를 다시 안 올린다
RUN java -Djarmode=layertools -jar build/libs/*.jar extract --destination /layers

# ── 실행 ────────────────────────────────────────────────────────
# JDK가 아니라 JRE. 이미지가 절반 이하로 줄고 컴파일러가 서버에 남지 않는다
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /layers/dependencies/ ./
COPY --from=build --chown=app:app /layers/spring-boot-loader/ ./
COPY --from=build --chown=app:app /layers/snapshot-dependencies/ ./
COPY --from=build --chown=app:app /layers/application/ ./
USER app

EXPOSE 8080

# 4GB 서버에 3개 서비스가 같이 산다. 컨테이너 메모리의 65%만 힙으로 쓴다
#   (나머지는 메타스페이스·코드캐시·스레드 스택 몫. 100%로 두면 OOM Killer에 잡힌다)
# SerialGC: 2vCPU + 작은 힙에서는 G1보다 메모리·CPU 오버헤드가 작다. 트래픽이 낮아 지연은 문제되지 않는다
# ExitOnOutOfMemoryError: 힙이 터지면 좀비로 살아 있지 말고 죽어서 재시작되게 한다
ENTRYPOINT ["java", \
  "-XX:MaxRAMPercentage=65", \
  "-XX:+UseSerialGC", \
  "-XX:+ExitOnOutOfMemoryError", \
  "-Duser.timezone=Asia/Seoul", \
  "org.springframework.boot.loader.launch.JarLauncher"]
