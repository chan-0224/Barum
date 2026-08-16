package com.barum.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.servers.Server;

/**
 * Swagger UI. 개발·통합용이라 기본은 꺼져 있다.
 *
 * <p>기본값을 끔으로 둔 이유 — 켜는 걸 잊으면 개발이 조금 불편할 뿐이지만,
 * 끄는 걸 잊으면 심사 기간 내내 API 문서와 시험 호출 버튼이 공개된다.
 * 켜려면 {@code DOCS_ENABLED=true}.
 *
 * <p>익명 세션 토큰이 필요한 엔드포인트가 많아 Authorize 버튼을 붙여 둔다.
 * 토큰은 브라우저 콘솔에서 Supabase 클라이언트로 뽑거나,
 * {@code POST {SUPABASE_URL}/auth/v1/signup} 에 apikey 헤더만 넣고 빈 본문을 보내면 나온다.
 */
@Configuration
@ConditionalOnProperty(name = "springdoc.swagger-ui.enabled", havingValue = "true")
public class SwaggerConfig {

    @Value("${barum.docs.server-url:}")
    private String serverUrl;

    @Bean
    OpenAPI barumOpenApi() {
        SecurityScheme bearer = new SecurityScheme()
                .type(SecurityScheme.Type.HTTP)
                .scheme("bearer")
                .bearerFormat("JWT")
                .description("""
                        Supabase 익명 세션 access_token.

                        토큰 얻는 법:
                          curl -X POST "{SUPABASE_URL}/auth/v1/signup" \\
                               -H "apikey: {SUPABASE_ANON_KEY}" \\
                               -H "Content-Type: application/json" -d '{}'
                        응답의 access_token 을 Authorize에 붙여넣는다. Bearer 접두사는 빼고 값만.""");

        OpenAPI api = new OpenAPI()
                .info(new Info()
                        .title("바름 API")
                        .version("0.1.0")
                        .description("""
                                프론트 ↔ Spring. 명세 원본은 `docs/API.md`.

                                - 로그인이 없다. 진입 시 Supabase 익명 세션을 발급받아 그 토큰을 쓴다
                                - 카탈로그 조회는 토큰 없이도 된다
                                - 루틴 생성(SSE)은 Spring이 아니라 AI 서버를 직접 호출한다. 여기 없다"""))
                .components(new Components().addSecuritySchemes("bearerAuth", bearer))
                .addSecurityItem(new SecurityRequirement().addList("bearerAuth"));

        // 외부 주소로 열어 두면 Swagger의 Try it out이 그 주소로 나간다.
        // 비워 두면 브라우저가 보고 있는 주소를 그대로 쓴다
        if (serverUrl != null && !serverUrl.isBlank()) {
            api.addServersItem(new Server().url(serverUrl));
        }
        return api;
    }
}
