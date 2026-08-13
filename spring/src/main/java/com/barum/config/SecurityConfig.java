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
        c.setAllowedOrigins(allowedOrigins);
        c.setAllowedMethods(List.of("GET", "POST", "DELETE", "PATCH", "OPTIONS"));
        c.setAllowedHeaders(List.of("Authorization", "Content-Type"));
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
