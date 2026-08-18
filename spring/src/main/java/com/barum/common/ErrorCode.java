package com.barum.common;

import org.springframework.http.HttpStatus;

/** docs/API.md 에러 코드 표. 이 목록 밖의 코드를 프론트로 내보내지 않는다. */
public enum ErrorCode {
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "로그인 정보가 만료되었습니다."),
    VALIDATION_ERROR(HttpStatus.BAD_REQUEST, "요청 값을 확인해 주세요."),
    PRODUCT_NOT_FOUND(HttpStatus.NOT_FOUND, "제품을 찾을 수 없습니다."),
    EMPTY_VANITY(HttpStatus.CONFLICT, "화장대에 등록된 제품이 없습니다."),
    VANITY_FULL(HttpStatus.CONFLICT, "화장대가 가득 찼습니다."),
    DUPLICATE_PRODUCT(HttpStatus.CONFLICT, "이미 화장대에 있는 제품입니다."),
    RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "요청이 많습니다. 잠시 후 다시 시도해 주세요."),
    OCR_NO_TEXT(HttpStatus.UNPROCESSABLE_ENTITY, "전성분표를 읽지 못했습니다."),
    AI_TIMEOUT(HttpStatus.GATEWAY_TIMEOUT, "분석이 지연되고 있습니다. 다시 시도해 주세요."),
    EXTERNAL_API_ERROR(HttpStatus.BAD_GATEWAY, "정보를 불러오지 못했습니다.");

    private final HttpStatus status;
    private final String message;

    ErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    public HttpStatus status() {
        return status;
    }

    public String message() {
        return message;
    }
}
