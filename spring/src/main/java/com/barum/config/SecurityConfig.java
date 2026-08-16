package com.barum.config;

import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * 익명 세션 JWT 검증 + CORS.
 *
 * <p>프론트가 Supabase {@code signInAnonymously()}로 받은 토큰을 그대로 보낸다.
 * 검증은 JWKS(공개키)로 한다 — 서버가 JWT 시크릿을 들고 있을 필요가 없다.
 */
@Configuration
public class SecurityConfig {

    @Value("${barum.cors.allowed-origins}")
    private List<String> allowedOrigins;

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
                .csrf(csrf -> csrf.disable())  // 토큰 기반이고 쿠키를 쓰지 않는다
                .cors(cors -> cors.configurationSource(corsSource()))
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/actuator/health", "/api/v1/health").permitAll()
                        // DOCS_ENABLED=false면 springdoc이 아예 매핑을 만들지 않아 404가 된다.
                        // 여기서 열어 두는 것만으로 문서가 노출되지는 않는다
                        .requestMatchers("/swagger-ui.html", "/swagger-ui/**", "/v3/api-docs/**").permitAll()
                        // 카탈로그는 참조 데이터라 토큰 없이도 열어둔다. 화장대를 만들기 전에
                        // 제품을 둘러볼 수 있어야 하고, 어차피 유저 데이터가 아니다.
                        .requestMatchers("/api/v1/catalog/**").permitAll()
                        .anyRequest().authenticated())
                .oauth2ResourceServer(oauth -> oauth
                        .jwt(jwt -> {})
                        // 인증 실패도 docs/API.md 형식으로 내보낸다
                        .authenticationEntryPoint((req, res, e) -> writeUnauthorized(res)))
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint((req, res, e) -> writeUnauthorized(res)));
        return http.build();
    }

    private void writeUnauthorized(jakarta.servlet.http.HttpServletResponse res) throws java.io.IOException {
        res.setStatus(HttpStatus.UNAUTHORIZED.value());
        res.setContentType(MediaType.APPLICATION_JSON_VALUE);
        res.setCharacterEncoding("UTF-8");
        res.getWriter().write("{\"code\":\"UNAUTHORIZED\",\"message\":\"로그인 정보가 만료되었습니다.\"}");
    }

    @Bean
    CorsConfigurationSource corsSource() {
        CorsConfiguration c = new CorsConfiguration();
        // setAllowedOrigins가 아니라 패턴을 쓴다. 정확한 주소도 그대로 동작하고,
        // 개발 중에는 http://localhost:* 처럼 포트를 열어 둘 수 있다.
        //
        // 목록에 없는 오리진은 프리플라이트(OPTIONS)가 403으로 끊긴다. 실제 요청이 나가기 전이라
        // 서버 로그에도 흔적이 적어 원인을 찾기 어렵다. 흔한 함정 두 가지:
        //   - 프론트 개발 서버 포트가 3000이 아닐 때(Vite 5173 등)
        //   - localhost 대신 127.0.0.1로 접속할 때. CORS에서 이 둘은 다른 오리진이다
        c.setAllowedOriginPatterns(allowedOrigins);
        c.setAllowedMethods(List.of("GET", "POST", "DELETE", "PATCH", "OPTIONS"));
        // 목록으로 두면 브라우저가 요청한 헤더 중 목록에 없는 게 하나라도 있을 때 프리플라이트가
        // 깨진다. Accept를 빠뜨려서 실제로 한 번 겪었다 — axios·fetch가 자동으로 붙이는 헤더까지
        // 전부 예측해서 적는 건 불가능하다. "*"면 요청한 헤더를 그대로 되돌려준다.
        //
        // 느슨해 보이지만 위험하지 않다. 헤더를 허용한다고 서버가 그 헤더를 신뢰하는 게 아니고,
        // 접근 통제는 오리진 목록과 JWT가 한다.
        c.setAllowedHeaders(List.of("*"));
        c.setMaxAge(3600L);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", c);
        return source;
    }

    private static org.springframework.security.oauth2.jwt.Jwt token() {
        var auth = org.springframework.security.core.context.SecurityContextHolder
                .getContext().getAuthentication();
        if (auth instanceof org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken t) {
            return t.getToken();
        }
        throw new com.barum.common.ApiException(com.barum.common.ErrorCode.UNAUTHORIZED);
    }

    /** 익명 세션의 user_id(sub). 이 값이 곧 DB의 auth.uid()다. */
    public static String currentUserId() {
        Map<String, Object> claims = token().getClaims();
        Object sub = claims.get("sub");
        if (sub == null) {
            throw new com.barum.common.ApiException(com.barum.common.ErrorCode.UNAUTHORIZED);
        }
        return sub.toString();
    }

    /** 원본 JWT 문자열. Storage를 사용자 권한으로 호출할 때 그대로 실어 보낸다. */
    public static String currentJwt() {
        return token().getTokenValue();
    }
}
