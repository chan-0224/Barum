package com.barum.common;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** 모든 에러를 docs/API.md 형식 {code, message}로 통일한다. */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    private ResponseEntity<Map<String, String>> body(ErrorCode code, String message) {
        return ResponseEntity.status(code.status())
                .body(Map.of("code", code.name(), "message", message));
    }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, String>> handleApi(ApiException e) {
        return body(e.code(), e.getMessage());
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, MethodArgumentTypeMismatchException.class})
    public ResponseEntity<Map<String, String>> handleValidation(Exception e) {
        return body(ErrorCode.VALIDATION_ERROR, ErrorCode.VALIDATION_ERROR.message());
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, String>> handleNotFound(NoResourceFoundException e) {
        return body(ErrorCode.VALIDATION_ERROR, "존재하지 않는 경로입니다.");
    }

    /**
     * 마지막 그물. 스택트레이스는 서버 로그에만 남기고 클라이언트에는 코드만 준다.
     * 예외 메시지를 그대로 흘리면 DB 구조나 내부 URL이 노출된다.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handleUnexpected(Exception e) {
        log.error("처리되지 않은 예외", e);
        return body(ErrorCode.EXTERNAL_API_ERROR, "일시적인 오류가 발생했습니다.");
    }
}
