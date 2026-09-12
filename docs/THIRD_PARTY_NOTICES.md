# 제3자 코드·데이터

## 코드

Python·JavaScript 의존성은 `backend/requirements.txt`, `frontend/package.json`, `frontend/package-lock.json`에 기록되어 있습니다. 각 의존성의 라이선스는 해당 프로젝트의 고지를 따릅니다. 새 라이선스로 묶어 덮어쓰지 않습니다.

`backend/app/_vendor/pypdf_5_9_0.zip`은 기존 문서 추출 경로가 참조하는 배포 파일입니다. 대응 고지 `backend/app/_vendor/pypdf_LICENSE.txt`와 `README.txt`를 함께 보존합니다. 일반 설치 ZIP을 제외하는 규칙에서 이 경로만 예외입니다.

프로젝트 자체에 대한 LICENSE는 이번 문서 패키지가 임의로 부여하지 않습니다. 저장소 소유자가 재사용 허용 범위를 정한 뒤 별도로 선택해야 합니다.

## 데이터·예시

Yahoo Finance, SEC, 회사 IR, 웹 검색으로 얻은 원문과 데이터는 이 프로젝트의 소유물이 아닙니다. 서비스의 이용조건 및 데이터 재배포 조건을 확인해야 합니다. 개인 캐시·전체 기사·전체 원문 공시 묶음을 공개 저장소에 넣지 않습니다.

기존 `backend/data/filing_excerpt_examples080.json`과 테스트 fixtures는 예시·회귀 테스트 입력입니다. 최신 기업 조사나 주가 판단으로 해석하지 않습니다. 출처 고지와 원래 파일을 보존하며, 제공 범위가 아닌 개인 다운로드 자료를 추가하지 않습니다.

시연 캡처에는 필요한 UI와 짧은 출처 연결만 사용합니다. 계좌·API 키·개인 경로·이메일은 노출하지 않습니다. 원문 내용의 대량 재배포는 피합니다.
